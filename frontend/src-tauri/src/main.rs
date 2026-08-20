#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{fs, net::TcpListener, sync::Mutex};
use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, State, WebviewWindow};
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use uuid::Uuid;

struct RuntimeState {
    child: Mutex<Option<CommandChild>>,
    token: String,
    port: u16,
}

#[derive(Serialize)]
struct RuntimeConnection {
    token: String,
    port: u16,
}

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

#[tauri::command]
fn runtime_connection(state: State<'_, RuntimeState>) -> RuntimeConnection {
    RuntimeConnection {
        token: state.token.clone(),
        port: state.port,
    }
}

fn reserve_local_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    listener.local_addr().map(|address| address.port()).map_err(|error| error.to_string())
}

fn start_runtime(app: &AppHandle, state: State<'_, RuntimeState>) {
    let data_dir = match app.path().app_data_dir() {
        Ok(path) => path,
        Err(error) => {
            eprintln!("Unable to resolve application data directory: {error}");
            return;
        }
    };

    if let Err(error) = fs::create_dir_all(&data_dir) {
        eprintln!("Unable to create application data directory: {error}");
        return;
    }

    let data_dir = data_dir.to_string_lossy().into_owned();
    match app.shell().sidecar("agent-runtime") {
        Ok(command) => match command
            .env("AGENT_DATA_DIR", data_dir)
            .env("AGENT_RUNTIME_TOKEN", state.token.clone())
            .env("AGENT_PORT", state.port.to_string())
            .spawn()
        {
            Ok((_events, child)) => *state.child.lock().expect("runtime lock poisoned") = Some(child),
            Err(error) => eprintln!("Agent runtime unavailable: {error}"),
        },
        Err(error) => eprintln!("Agent runtime sidecar unavailable: {error}"),
    }
}

fn stop_runtime(app: &AppHandle) {
    let state = app.state::<RuntimeState>();
    if let Some(child) = state.child.lock().expect("runtime lock poisoned").take() {
        let _ = child.kill();
    }
}

fn main() {
    let port = reserve_local_port().expect("unable to reserve a local runtime port");
    tauri::Builder::default()
        .manage(RuntimeState {
            child: Mutex::new(None),
            token: Uuid::new_v4().simple().to_string(),
            port,
        })
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<RuntimeState>();
            start_runtime(&handle, state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![set_always_on_top, toggle_sidebar, runtime_connection])
        .run(|app, event| {
            if matches!(event, RunEvent::Exit { .. }) {
                stop_runtime(app);
            }
        })
        .expect("error while running Personal Assistant");
}
