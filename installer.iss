; Inno Setup — génère Output\Smart_DEM_Setup.exe
; La version est injectée par le workflow : iscc /DAppVersion=1.0.0 installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Installation dans le profil utilisateur : la mise à jour en direct n'exige pas les droits administrateur.
[Setup]
AppName=Smart DEM
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Smart_DEM
DefaultGroupName=Smart DEM
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Smart_DEM_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\Smart_DEM\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autodesktop}\Smart DEM"; Filename: "{app}\Smart_DEM.exe"
Name: "{group}\Smart DEM"; Filename: "{app}\Smart_DEM.exe"

[Run]
Filename: "{app}\Smart_DEM.exe"; Description: "Lancer Smart DEM"; Flags: postinstall nowait skipifsilent
