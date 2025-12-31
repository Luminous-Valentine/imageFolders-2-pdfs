<##
This launcher reads directory settings from tool_settings.txt (legacy: reference_paths.txt) and runs folder2pdf.py.

Directory roles (from settings file):
- INPUT_DIR: contains subfolders of images to convert
- OUTPUT_DIR: destination for generated PDFs
##>

param(
    [Parameter(Mandatory = $false)]
    [string]$InputDir,

    [Parameter(Mandatory = $false)]
    [string]$OutputDir
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

    # ${KEY} substitution
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

    # KEY-as-value reference (e.g. EXTRACT_INPUT_DIR=INPUT_DIR)
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

$scriptRoot = Get-ScriptRoot
$configPath = Ensure-SettingsFile -ScriptRoot $scriptRoot
$config = Read-ReferencePaths -ConfigPath $configPath

$backend = $config['FOLDER2PDF_BACKEND']
if ([string]::IsNullOrWhiteSpace($backend)) { $backend = 'img2pdf' }
$backend = $backend.Trim().ToLowerInvariant()
if ($backend -notin @('img2pdf','pikepdf')) { $backend = 'img2pdf' }

if (-not $InputDir) {
    $inputValue = $config['INPUT_DIR']
    if ([string]::IsNullOrWhiteSpace($inputValue)) { $inputValue = '01_images_input' }
    $inputValue = Expand-ReferenceValue -Config $config -Value $inputValue
    $InputDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $inputValue
}

if (-not $OutputDir) {
    $outputValue = $config['OUTPUT_DIR']
    if ([string]::IsNullOrWhiteSpace($outputValue)) { $outputValue = '01_pdf_output' }
    $outputValue = Expand-ReferenceValue -Config $config -Value $outputValue
    $OutputDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $outputValue
}

$py = Join-Path $scriptRoot 'src\\folder2pdf.py'

Write-Host ("INFO: Input directory: {0}" -f $InputDir)
Write-Host ("INFO: Output directory: {0}" -f $OutputDir)
Write-Host ("INFO: Backend: {0}" -f $backend)

& python $py $InputDir $OutputDir --ref $configPath --backend $backend
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { exit $exitCode }
