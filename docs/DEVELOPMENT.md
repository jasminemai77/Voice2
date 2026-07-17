# Development environment and disk layout

Voice2 targets Windows 10/11. The web/API path needs Python 3.11–3.13 and Node.js 22+. Tauri desktop builds additionally need Rust stable-msvc, Microsoft C++ Build Tools with the Desktop development with C++ workload, the Windows SDK, and WebView2.

## Recommended disk split

Keep language runtimes and OS-integrated components in their supported default locations, but move high-churn caches, build outputs, models, and user data to a spacious data drive.

Example for a machine with a large `G:` drive:

```powershell
npm config set cache "G:\npm-cache" --location=user
npm config set prefix "G:\npm-global" --location=user

[Environment]::SetEnvironmentVariable("CARGO_HOME", "G:\cargo-home", "User")
[Environment]::SetEnvironmentVariable("CARGO_TARGET_DIR", "G:\cargo-target", "User")
[Environment]::SetEnvironmentVariable("VOICE2_DATA_DIR", "G:\Voice2Data", "User")
```

- Rustup and the stable-msvc compiler may remain under `%USERPROFILE%\.rustup` on the system drive.
- Install the Visual Studio Build Tools product to the large drive when space is constrained. Some shared Installer and Windows SDK files still use the system drive.
- `node_modules` remains project-local. npm downloads and global tools use the configured cache/prefix.
- `VOICE2_DATA_DIR` contains local reference voices, indexes, tuning data, and future model-manager state. Never commit it.

Restart terminals after changing user environment variables. Verify the desktop environment with:

```powershell
npx tauri info
npm run desktop:build -- --no-bundle
```

CI runs the same no-bundle desktop compile on `windows-latest`, in addition to Python and web quality gates.

## Optional VoxCPM model process

VoxCPM requires Python below 3.13, so it runs outside the Python 3.13 API environment. A typical local layout is:

```powershell
[Environment]::SetEnvironmentVariable("VOICE2_VOXCPM_PYTHON", "G:\Voice2Data\envs\voxcpm\Scripts\python.exe", "User")
[Environment]::SetEnvironmentVariable("VOICE2_VOXCPM_MODEL", "G:\Voice2Data\models\VoxCPM-0.5B", "User")
[Environment]::SetEnvironmentVariable("HF_HOME", "G:\Voice2Data\cache\huggingface", "User")
[Environment]::SetEnvironmentVariable("TORCH_HOME", "G:\Voice2Data\cache\torch", "User")
```

Set `VOICE2_ENABLE_VOXCPM=1` only after the runtime passes dependency and CUDA checks. Availability does not bypass Voice2's measured RAM/VRAM safety budget.
