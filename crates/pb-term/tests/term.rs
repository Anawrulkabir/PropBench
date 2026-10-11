//! A shell in the pseudo-terminal runs commands and sees the project environment first on PATH; the parent's
//! PATH is not changed.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::time::{Duration, Instant};

use pb_term::{Terminal, activated_env, activation_command, default_shell};

/// Collect output until `needle` appears, answering cursor-position queries (`ESC[6n`) as a terminal emulator
/// does: Windows' ConPTY sends one at start-up and waits for the reply before the shell reads input (xterm.js
/// answers it in the app).
fn read_until(term: &Terminal, rx: &std::sync::mpsc::Receiver<Vec<u8>>, needle: &str, limit: Duration) -> String {
    let start = Instant::now();
    let mut text = String::new();
    while start.elapsed() < limit {
        if let Ok(chunk) = rx.recv_timeout(Duration::from_millis(100)) {
            let chunk = String::from_utf8_lossy(&chunk);
            for _ in 0..chunk.matches("\x1b[6n").count() {
                term.write(b"\x1b[1;1R").unwrap();
            }
            text.push_str(&chunk);
            if text.contains(needle) {
                break;
            }
        }
    }
    text
}

#[test]
fn shell_runs_inside_the_environment() {
    let dir = std::env::temp_dir().join(format!("pb-term-{}", std::process::id()));
    let bin = dir.join(if cfg!(windows) { "Scripts" } else { "bin" });
    std::fs::create_dir_all(&bin).unwrap();
    let path_before = std::env::var_os("PATH");
    let env = activated_env(&dir, &bin);
    let shell = default_shell();
    let (term, rx) = Terminal::spawn(&shell, &[], &dir, &env, 120, 30).unwrap();
    if cfg!(windows) {
        read_until(&term, &rx, "\x1b[6n", Duration::from_secs(10)); // answer ConPTY's start-up query first
    }
    term.write(activation_command(&shell, &dir, &bin).as_bytes()).unwrap();
    // The terminal echoes what is typed: wait for text that only the shell's expansion produces.
    let (probe, done) = if cfg!(windows) {
        ("echo VENV=%VIRTUAL_ENV% & echo END_%OS%\r\n", "END_Windows_NT")
    } else {
        (
            "echo VENV=$VIRTUAL_ENV; echo FIRST=${PATH%%:*}; echo END_$((40+2))\n",
            "END_42",
        )
    };
    term.write(probe.as_bytes()).unwrap();
    let out = read_until(&term, &rx, done, Duration::from_secs(20));
    let expected = format!("VENV={}", dir.display());
    assert!(out.contains(&expected), "{out}");
    if !cfg!(windows) {
        assert!(out.contains(&format!("FIRST={}", bin.display())), "{out}");
    }
    term.resize(100, 40).unwrap();
    term.write(if cfg!(windows) { b"exit\r\n" } else { b"exit\n" }).unwrap();
    let start = Instant::now();
    while term.exited().is_none() && start.elapsed() < Duration::from_secs(20) {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(term.exited().is_some(), "the shell ended");
    assert_eq!(std::env::var_os("PATH"), path_before, "the parent's PATH is untouched");
}
