use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

struct Backend(Mutex<Option<Child>>);

fn start_backend() -> Option<Child> {
    let python = std::env::var("VOICE2_PYTHON").unwrap_or_else(|_| "python".to_string());
    Command::new(python)
        .args(["-m", "voice2.main"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .ok()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(Backend(Mutex::new(start_backend())));
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                let backend = window.app_handle().state::<Backend>();
                if let Ok(mut guard) = backend.0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                    }
                };
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run Voice2 desktop application");
}
