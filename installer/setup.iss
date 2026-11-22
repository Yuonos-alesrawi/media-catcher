; Media Catcher installer (Inno Setup 6.3+)
; Compiled by build.ps1, which passes AppVersion / SourceDir / OutputDir.

; When compiled by hand (not through build.ps1), take the values from build_defines.iss.
#ifndef AppVersion
  #if FileExists(AddBackslash(SourcePath) + "build_defines.iss")
    #include "build_defines.iss"
  #endif
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\app"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{8F2A6C14-5B7E-4D39-9A61-3C0E2B7D4F58}
AppName=Media Catcher
AppVersion={#AppVersion}
AppPublisher=Media Catcher
; Per-user install: no admin rights, and the app can update yt-dlp inside its own folder.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\MediaCatcher
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=MediaCatcher-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Media Catcher
; The app creates this mutex; Setup/Uninstall ask the user to close the app if it is running.
AppMutex=MediaCatcherMutex

[Tasks]
Name: "autostart"; Description: "Start Media Catcher when I sign in to Windows (recommended)"; GroupDescription: "Options:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Media Catcher"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"
Name: "{autoprograms}\Media Catcher - browser extension folder"; Filename: "{app}\extension"
Name: "{autoprograms}\Media Catcher - debug console"; Filename: "{app}\debug.bat"; WorkingDir: "{app}"
Name: "{autoprograms}\Media Catcher - stop"; Filename: "{app}\stop.bat"; WorkingDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MediaCatcher"; \
    ValueData: """{app}\python\pythonw.exe"" ""{app}\app.py"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; \
    Description: "Start Media Catcher now"; Flags: nowait postinstall skipifsilent
Filename: "{app}\extension"; Description: "Open the browser extension folder (for chrome://extensions > Load unpacked)"; \
    Flags: postinstall shellexec skipifsilent unchecked

[UninstallDelete]
; Files created after installation (pip updates, caches, logs). Downloaded videos are never touched.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{localappdata}\MediaCatcher"
