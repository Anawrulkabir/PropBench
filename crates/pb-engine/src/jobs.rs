//! Jobs, the result cache and the job graph (README §4b).
//!
//! A job is one worker operation with its parameters. Jobs are deterministic given their parameters (which
//! include every seed), so a job's key, a hash of method, parameters and worker version, names its result: a
//! cached result is reused instead of recomputed. When the worker dies during a job, the job is retried once on a
//! fresh worker; finished jobs are already in the cache, so an interrupted study resumes where it stopped.

use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicBool, Ordering};

use pb_store::ResultCache;
use serde::Serialize;
use serde_json::Value;

use crate::{Engine, EngineError, Method};

/// JSON with object keys sorted at every level and no whitespace: equal values give equal text.
pub fn canonical_json(value: &Value) -> String {
    fn write(value: &Value, out: &mut String) {
        match value {
            Value::Object(map) => {
                out.push('{');
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                for (i, key) in keys.into_iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    out.push_str(&Value::String(key.clone()).to_string());
                    out.push(':');
                    if let Some(v) = map.get(key) {
                        write(v, out);
                    }
                }
                out.push('}');
            }
            Value::Array(items) => {
                out.push('[');
                for (i, v) in items.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write(v, out);
                }
                out.push(']');
            }
            other => out.push_str(&other.to_string()),
        }
    }
    let mut out = String::new();
    write(value, &mut out);
    out
}

/// 64-bit FNV-1a with a chosen offset basis.
fn fnv1a(bytes: &[u8], basis: u64) -> u64 {
    bytes
        .iter()
        .fold(basis, |h, b| (h ^ u64::from(*b)).wrapping_mul(0x0100_0000_01b3))
}

/// Key of a job: 128 bits (two FNV-1a hashes) over the method, the canonical parameters and the worker version.
pub fn job_key(method: Method, params: &Value, worker_version: &str) -> String {
    let text = format!("{}\n{}\n{}", method.name(), worker_version, canonical_json(params));
    let a = fnv1a(text.as_bytes(), 0xcbf2_9ce4_8422_2325);
    let b = fnv1a(text.as_bytes(), 0x6c62_272e_07bb_0142);
    format!("{a:016x}{b:016x}")
}

impl Method {
    /// Operations whose results are worth caching: deterministic and possibly slow.
    pub fn cacheable(self) -> bool {
        matches!(
            self,
            Method::ModelFit
                | Method::StudyValidate
                | Method::ConsistencyAnalyze
                | Method::ModelCompare
                | Method::DatasetCheck
                | Method::ModelPredict
        )
    }
}

impl Engine {
    /// Like `invoke`, with the result cache: a cacheable job whose key is cached is not sent to the worker, and a
    /// job interrupted by a worker crash is retried once on a fresh worker. Returns the result and whether it came
    /// from the cache. Cache read or write errors only cost the cache, never the result.
    pub async fn invoke_cached(
        &self,
        method: Method,
        params: Value,
        cache: Option<&ResultCache>,
    ) -> Result<(Value, bool), EngineError> {
        let cache = cache.filter(|_| method.cacheable());
        let key = match cache {
            Some(_) => {
                let info = self.start().await?;
                Some(job_key(
                    method,
                    &params,
                    &format!("{}/{}", info.propbench, info.protocol),
                ))
            }
            None => None,
        };
        if let (Some(cache), Some(key)) = (cache, key.as_deref())
            && let Ok(Some(hit)) = cache.get(key)
        {
            return Ok((hit, true));
        }
        let result = match self.invoke(method, params.clone()).await {
            Err(EngineError::WorkerExited(_)) => self.invoke(method, params).await,
            other => other,
        }?;
        if let (Some(cache), Some(key)) = (cache, key.as_deref())
            && let Err(err) = cache.put(key, method.name(), &result)
        {
            eprintln!("[propbench engine] result not cached: {err}");
        }
        Ok((result, false))
    }
}

/// One job of a graph: an id, a worker operation and the ids of jobs that must finish first.
#[derive(Debug, Clone)]
pub struct Job {
    pub id: String,
    pub method: Method,
    pub params: Value,
    pub after: Vec<String>,
}

/// What became of one job.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum JobOutcome {
    Done {
        result: Value,
        cached: bool,
    },
    Failed {
        message: String,
    },
    /// A job it depends on failed or the run was cancelled.
    Skipped {
        reason: String,
    },
}

/// Progress of a graph run, for the UI's output panel and the CLI.
#[derive(Debug, Clone, Serialize)]
pub struct JobEvent {
    pub id: String,
    pub index: usize,
    pub total: usize,
    pub outcome: JobOutcome,
}

/// Jobs with dependencies, run one at a time in a deterministic order (insertion order among ready jobs). The
/// worker itself parallelises inside a job (e.g. cross-validation folds), CLAUDE.md rule 7.
#[derive(Debug, Default, Clone)]
pub struct JobGraph {
    jobs: Vec<Job>,
}

impl JobGraph {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a job. Ids must be unique and dependencies must already be in the graph (so there are no cycles).
    pub fn add(&mut self, job: Job) -> Result<(), EngineError> {
        let invalid = |message: String| EngineError::Rpc {
            code: EngineError::INVALID_PARAMS,
            message,
        };
        if self.jobs.iter().any(|j| j.id == job.id) {
            return Err(invalid(format!("job `{}` is defined twice", job.id)));
        }
        if let Some(missing) = job.after.iter().find(|d| !self.jobs.iter().any(|j| &j.id == *d)) {
            return Err(invalid(format!("job `{}` depends on unknown job `{missing}`", job.id)));
        }
        self.jobs.push(job);
        Ok(())
    }

    pub fn len(&self) -> usize {
        self.jobs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.jobs.is_empty()
    }

    /// Run every job. `cancel` stops the run before the next job (set it and call `Engine::cancel` to stop the
    /// current one too). `progress` is called after each job.
    pub async fn run(
        &self,
        engine: &Engine,
        cache: Option<&ResultCache>,
        cancel: &AtomicBool,
        mut progress: impl FnMut(&JobEvent),
    ) -> BTreeMap<String, JobOutcome> {
        let mut outcomes: BTreeMap<String, JobOutcome> = BTreeMap::new();
        let mut failed: BTreeSet<&str> = BTreeSet::new();
        let total = self.jobs.len();
        // Jobs were added after their dependencies, so insertion order is a valid topological order.
        for (index, job) in self.jobs.iter().enumerate() {
            let outcome = if cancel.load(Ordering::SeqCst) {
                JobOutcome::Skipped {
                    reason: "cancelled".into(),
                }
            } else if let Some(dep) = job.after.iter().find(|d| failed.contains(d.as_str())) {
                JobOutcome::Skipped {
                    reason: format!("`{dep}` did not finish"),
                }
            } else {
                match engine.invoke_cached(job.method, job.params.clone(), cache).await {
                    Ok((result, cached)) => JobOutcome::Done { result, cached },
                    Err(EngineError::Cancelled) => JobOutcome::Skipped {
                        reason: "cancelled".into(),
                    },
                    Err(err) => JobOutcome::Failed {
                        message: err.to_string(),
                    },
                }
            };
            if !matches!(outcome, JobOutcome::Done { .. }) {
                failed.insert(job.id.as_str());
            }
            progress(&JobEvent {
                id: job.id.clone(),
                index,
                total,
                outcome: outcome.clone(),
            });
            outcomes.insert(job.id.clone(), outcome);
        }
        outcomes
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn canonical_json_ignores_key_order_and_whitespace() {
        let a: Value = serde_json::from_str(r#"{"b": [1, {"y": 2, "x": 1}], "a": "s"}"#).unwrap_or_default();
        let b: Value = serde_json::from_str(r#"{"a":"s","b":[1,{"x":1,"y":2}]}"#).unwrap_or_default();
        assert_eq!(canonical_json(&a), canonical_json(&b));
        assert_eq!(canonical_json(&a), r#"{"a":"s","b":[1,{"x":1,"y":2}]}"#);
    }

    #[test]
    fn job_keys_depend_on_method_params_and_version() {
        let p = json!({"seed": 1, "model": {"kind": "ecs_viscosity"}});
        let k = job_key(Method::ModelFit, &p, "0.1/2");
        assert_eq!(k.len(), 32);
        assert_eq!(
            k,
            job_key(
                Method::ModelFit,
                &json!({"model": {"kind": "ecs_viscosity"}, "seed": 1}),
                "0.1/2"
            )
        );
        assert_ne!(k, job_key(Method::StudyValidate, &p, "0.1/2"));
        assert_ne!(
            k,
            job_key(
                Method::ModelFit,
                &json!({"seed": 2, "model": {"kind": "ecs_viscosity"}}),
                "0.1/2"
            )
        );
        assert_ne!(k, job_key(Method::ModelFit, &p, "0.2/2"));
    }

    #[test]
    fn graph_refuses_duplicates_and_unknown_dependencies() {
        let job = |id: &str, after: &[&str]| Job {
            id: id.into(),
            method: Method::ModelKinds,
            params: Value::Null,
            after: after.iter().map(|s| (*s).to_owned()).collect(),
        };
        let mut g = JobGraph::new();
        assert!(g.add(job("a", &[])).is_ok());
        assert!(g.add(job("a", &[])).is_err());
        assert!(g.add(job("b", &["missing"])).is_err());
        assert!(g.add(job("b", &["a"])).is_ok());
        assert_eq!(g.len(), 2);
    }
}
