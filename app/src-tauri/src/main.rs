// Goblin Yapper desktop shell.
//
// Starts the bundled Python backend (sidecar) with a per-user data dir, waits for it to
// listen, then points the window at the panel it serves. If something is already
// listening on the port (e.g. a dev backend run from Python with the GPU TTS installed),
// the app just attaches to it instead of starting its own.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, Url, WebviewWindow};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const PORT: u16 = 8765;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);

struct Backend(Mutex<Option<CommandChild>>);

fn backend_up() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn show_error(window: &WebviewWindow, msg: &str) {
    let js = format!("window.showError && window.showError({:?})", msg);
    let _ = window.eval(&js);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let window = app.get_webview_window("main").expect("main window");
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let log_path = data_dir.join("goblin-yapper.log");

            if !backend_up() {
                let (mut rx, child) = app
                    .shell()
                    .sidecar("goblin-yapper-server")?
                    .args([
                        "--data-dir".to_string(),
                        data_dir.to_string_lossy().into_owned(),
                        "--port".to_string(),
                        PORT.to_string(),
                        "--no-console".to_string(),
                        "--parent-pid".to_string(),
                        std::process::id().to_string(),
                    ])
                    .spawn()?;
                app.state::<Backend>().0.lock().unwrap().replace(child);

                let win = window.clone();
                let log = log_path.clone();
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        if let CommandEvent::Terminated(status) = event {
                            show_error(
                                &win,
                                &format!(
                                    "O servidor encerrou (código {:?}). Veja o log em {}",
                                    status.code,
                                    log.display()
                                ),
                            );
                        }
                    }
                });
            }

            std::thread::spawn(move || {
                let start = Instant::now();
                while start.elapsed() < STARTUP_TIMEOUT {
                    if backend_up() {
                        let url = Url::parse(&format!("http://127.0.0.1:{PORT}/panel")).unwrap();
                        let _ = window.navigate(url);
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(250));
                }
                show_error(
                    &window,
                    &format!("O servidor não respondeu. Veja o log em {}", log_path.display()),
                );
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Goblin Yapper")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
