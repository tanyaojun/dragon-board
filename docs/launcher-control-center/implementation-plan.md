# Dragon Board Launcher Control Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing WinForms launcher into a compact service control center with Redis monitoring, tray behavior, hotkey, autostart, and right-edge auto-hide.

**Architecture:** Keep the current `tools/DragonBoardLauncher` project. Implement service metadata, status polling, tray behavior, hotkey registration, autostart registry writes, and UI cards in `Program.cs` to avoid introducing a new UI framework.

**Tech Stack:** C# 12, .NET 8 Windows Forms, Windows registry HKCU Run, `sc.exe`, `netstat.exe`, `IPGlobalProperties`.

---

## Files

- Modify: `tools/DragonBoardLauncher/Program.cs`
- No project dependency changes expected.

## Tasks

- [ ] Replace the plain table layout with a compact dark service dashboard.
- [ ] Add Redis as a Windows service entry on port 6379.
- [ ] Add status model containing running state, PID list, process name and service state.
- [ ] Add tray icon, tray context menu and close-to-tray behavior.
- [ ] Add global hotkey `Ctrl+Alt+D`.
- [ ] Add HKCU Run autostart toggle.
- [ ] Add right-edge docking and mouse-hover auto expand/collapse.
- [ ] Add `Start Core`, `Start All`, `Stop Managed`, `Health Check`, `Open Board`, `Open Quant` actions.
- [ ] Build with `dotnet build tools/DragonBoardLauncher/DragonBoardLauncher.csproj`.

## Verification

```powershell
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj
```

Expected: build succeeds with 0 errors.
