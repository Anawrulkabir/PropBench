//! Credentials in the operating system's keychain (CLAUDE.md: never in project files or logs): the macOS
//! Keychain, the Windows Credential Manager, or the Secret Service on Linux. Names are short identifiers such as
//! `ai.openai` or `github.token`; values never leave this crate except to the code that needs them.

use thiserror::Error;

/// Keychain service under which PropBench stores its credentials.
pub const SERVICE: &str = "io.github.anawrulkabir.propbench";

#[derive(Debug, Error)]
pub enum SecretError {
    #[error("invalid credential name `{0}` (letters, digits, '.', '-', '_')")]
    InvalidName(String),
    #[error("keychain error: {0}")]
    Keychain(String),
}

fn entry(name: &str) -> Result<keyring::Entry, SecretError> {
    if name.is_empty()
        || name.len() > 64
        || !name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_'))
    {
        return Err(SecretError::InvalidName(name.to_owned()));
    }
    keyring::Entry::new(SERVICE, name).map_err(|e| SecretError::Keychain(e.to_string()))
}

pub fn set(name: &str, value: &str) -> Result<(), SecretError> {
    entry(name)?
        .set_password(value)
        .map_err(|e| SecretError::Keychain(e.to_string()))
}

/// The stored value, or `None` when there is none.
pub fn get(name: &str) -> Result<Option<String>, SecretError> {
    match entry(name)?.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(SecretError::Keychain(e.to_string())),
    }
}

pub fn has(name: &str) -> Result<bool, SecretError> {
    Ok(get(name)?.is_some())
}

pub fn delete(name: &str) -> Result<(), SecretError> {
    match entry(name)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(SecretError::Keychain(e.to_string())),
    }
}

/// Use an in-memory store (tests and machines without a keychain service).
pub fn use_mock_store() {
    keyring::set_default_credential_builder(keyring::mock::default_credential_builder());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_are_checked() {
        use_mock_store();
        assert!(matches!(set("bad name", "x"), Err(SecretError::InvalidName(_))));
        assert!(matches!(get(""), Err(SecretError::InvalidName(_))));
        assert!(matches!(has("../x"), Err(SecretError::InvalidName(_))));
    }

    #[test]
    fn missing_entries_are_none_and_delete_is_idempotent() -> Result<(), SecretError> {
        use_mock_store();
        assert_eq!(get("ai.none")?, None);
        delete("ai.none")?;
        Ok(())
    }
}
