<##
This launcher reads directory settings from tool_settings.txt (legacy: reference_paths.txt) and runs move_matched_pdfs.py.

Directory roles (from settings file):
- OUTPUT_DIR: folder with PDFs produced by folder2pdf.py (move source)
- OCR_DIR: folder containing OCR-processed PDFs (comparison source)
- MATCHED_DIR: folder to move matched PDFs into (destination)
##>

param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDir,

    [Parameter(Mandatory = $false)]
    [string]$ReferenceDir,

    [Parameter(Mandatory = $false)]
    [string]$DestinationDir
)

function Get-ScriptRoot {
    $scriptRoot = $PSScriptRoot
    if (-not [string]::IsNullOrWhiteSpace($scriptRoot)) { return $scriptRoot }

    if ($PSCommandPath) { return (Split-Path -Parent $PSCommandPath) }
    if ($MyInvocation.MyCommand.Path) { return (Split-Path -Parent $MyInvocation.MyCommand.Path) }

    return (Get-Location).Path
}

function Ensure-SettingsFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptRoot
    )

    $preferred = Join-Path $ScriptRoot 'tool_settings.txt'
    if (Test-Path -LiteralPath $preferred) { return $preferred }

    $legacy = Join-Path $ScriptRoot 'reference_paths.txt'
    if (Test-Path -LiteralPath $legacy) { return $legacy }

    $examplePath = Join-Path $ScriptRoot 'tool_settings.example.txt'
    if (Test-Path -LiteralPath $examplePath) {
        Copy-Item -LiteralPath $examplePath -Destination $preferred
        return $preferred
    }

    throw "tool_settings.txt not found (legacy: reference_paths.txt), and tool_settings.example.txt is missing."
}

function Read-ReferencePaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )

    $result = @{}
    $content = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    foreach ($rawLine in ($content -split "`r?`n")) {
        $line = $rawLine.Trim()
        if (-not $line) { continue }
        if ($line.StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim().ToUpperInvariant()
        $value = $line.Substring($idx + 1).Trim()
        $result[$key] = $value
    }
    return $result
}

function Expand-ReferenceValue {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config,

        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $false)]
        [string[]]$Stack = @()
    )

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith('"') -and $trimmed.EndsWith('"') -and $trimmed.Length -ge 2) {
        $trimmed = $trimmed.Substring(1, $trimmed.Length - 2)
    }

    $trimmed = [regex]::Replace($trimmed, '\$\{([^}]+)\}', {
        param($m)
        $var = $m.Groups[1].Value.Trim().ToUpperInvariant()
        if ($Stack -contains $var) {
            throw ("Detected cyclic reference in settings file: {0}" -f (($Stack + $var) -join ' -> '))
        }
        if (-not $Config.ContainsKey($var)) {
            throw ("Missing referenced key in settings file: {0}" -f $var)
        }
        return (Expand-ReferenceValue -Config $Config -Value $Config[$var] -Stack ($Stack + $var))
    })

    $maybeKey = $trimmed.ToUpperInvariant()
    if ($maybeKey -match '^[A-Z0-9_]+$' -and $Config.ContainsKey($maybeKey)) {
        if ($Stack -contains $maybeKey) {
            throw ("Detected cyclic reference in settings file: {0}" -f (($Stack + $maybeKey) -join ' -> '))
        }
        return (Expand-ReferenceValue -Config $Config -Value $Config[$maybeKey] -Stack ($Stack + $maybeKey))
    }

    return $trimmed
}

function Resolve-ConfiguredPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptRoot,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith('"') -and $trimmed.EndsWith('"') -and $trimmed.Length -ge 2) {
        $trimmed = $trimmed.Substring(1, $trimmed.Length - 2)
    }

    if ([System.IO.Path]::IsPathRooted($trimmed)) {
        return $trimmed
    }

    return (Join-Path $ScriptRoot $trimmed)
}

function Update-ReferencePathValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $lines = Get-Content -LiteralPath $ConfigPath -Encoding UTF8
    $updated = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) {
            $lines[$i] = ("{0}={1}" -f $Key, $Value)
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $lines += ("{0}={1}" -f $Key, $Value)
    }

    Set-Content -LiteralPath $ConfigPath -Value $lines -Encoding UTF8
}

$scriptRoot = Get-ScriptRoot
$configPath = Ensure-SettingsFile -ScriptRoot $scriptRoot
$config = Read-ReferencePaths -ConfigPath $configPath

if (-not $OutputDir) {
    $outputValue = $config['OUTPUT_DIR']
    if ([string]::IsNullOrWhiteSpace($outputValue)) { $outputValue = '01_pdf_output' }
    $outputValue = Expand-ReferenceValue -Config $config -Value $outputValue
    $OutputDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $outputValue
}

if (-not $DestinationDir) {
    $destValue = $config['MATCHED_DIR']
    if ([string]::IsNullOrWhiteSpace($destValue)) { $destValue = $config['SCANED_DIR'] }
    if ([string]::IsNullOrWhiteSpace($destValue)) { $destValue = '02_matched_pdfs' }
    $destValue = Expand-ReferenceValue -Config $config -Value $destValue
    $DestinationDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $destValue
}

if (-not $ReferenceDir) {
    $refValue = $config['OCR_DIR']
    if (-not [string]::IsNullOrWhiteSpace($refValue)) {
        $refValue = Expand-ReferenceValue -Config $config -Value $refValue
        $ReferenceDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $refValue
    }
}

if (-not $ReferenceDir) {
    Write-Host ''
    $ReferenceDir = Read-Host 'Enter OCR PDF directory path (you can paste/drag the folder path)'
}

if (-not $ReferenceDir) {
    Write-Error 'No directory provided. Aborting.'
    exit 1
}

$ReferenceDir = $ReferenceDir.Trim()
if ($ReferenceDir.StartsWith('"') -and $ReferenceDir.EndsWith('"') -and $ReferenceDir.Length -ge 2) {
    $ReferenceDir = $ReferenceDir.Substring(1, $ReferenceDir.Length - 2)
}

if (-not (Test-Path -LiteralPath $ReferenceDir)) {
    Write-Error ("Directory not found: {0}" -f $ReferenceDir)
    exit 1
}

Update-ReferencePathValue -ConfigPath $configPath -Key 'OCR_DIR' -Value $ReferenceDir

$py = Join-Path $scriptRoot 'src\\move_matched_pdfs.py'

Write-Host ("INFO: Output directory: {0}" -f $OutputDir)
Write-Host ("INFO: Reference directory: {0}" -f $ReferenceDir)
Write-Host ("INFO: Destination directory: {0}" -f $DestinationDir)

& python $py $OutputDir $ReferenceDir --destination $DestinationDir
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { exit $exitCode }
