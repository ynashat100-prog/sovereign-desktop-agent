use std::sync::Mutex;
use tauri::{AppHandle, Manager, State, WebviewWindow};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct RuntimeState(Mutex<Option<CommandChild>>);

#[tauri::command]
fn set_always_on_top(window: WebviewWindow, enabled: bool) -> Result<(), String> {
    window.set_always_on_top(enabled).map_err(|err| err.to_string())
}

#[tauri::command]
fn toggle_sidebar(app: AppHandle) -> Result<(), String> {
    let window = app.get_webview_window("main").ok_or("Main window not found")?;
    if window.is_visible().map_err(|err| err.to_string())? {
        window.hide().map_err(|err| err.to_string())?;
    } else {
        window.show().map_err(|err| err.to_string())?;
        window.set_focus().map_err(|err| err.to_string())?;
    }
    Ok(())
}

fn start_runtime(app: &AppHandle, state: State<'_, RuntimeState>) {
    match app.shell().sidecar("agent-runtime") {
        Ok(command) => match command.spawn() {
            Ok((_events, child)) => *state.0.lock().expect("runtime lock poisoned") = Some(child),
            Err(error) => eprintln!("Agent runtime unavailable; Demo Mode remains available: {error}"),
        },
        Err(error) => eprintln!("Agent runtime sidecar unavailable; Demo Mode remains available: {error}"),
    }
}

fn main() {
    tauri::Builder::default()
        .manage(RuntimeState(Mutex::new(None)))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<RuntimeState>();
            start_runtime(&handle, state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![set_always_on_top, toggle_sidebar])
        .run(tauri::generate_context!())
        .expect("error while running Sovereign Desktop Agent");
}
