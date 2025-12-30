<##
Interactive menu runner for folder2pdf (img2pdf) and optional carrier mode.

- Enter only: run with defaults read from tool_settings.txt (legacy: reference_paths.txt)
- Can configure options before running
##>

[CmdletBinding()]
param(
    [switch]$RunDefault
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

function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config,

        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter(Mandatory = $true)]
        [string]$Default
    )

    $k = $Key.Trim().ToUpperInvariant()
    if (-not $Config.ContainsKey($k)) { return $Default }
    $v = $Config[$k]
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return $v
}

function Parse-Int {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [int]$Default
    )
    try {
        return [int]$Value
    } catch {
        return $Default
    }
}

function Parse-Double {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [double]$Default
    )
    try {
        return [double]$Value
    } catch {
        return $Default
    }
}

function Parse-Bool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [bool]$Default
    )

    if ([string]::IsNullOrWhiteSpace($Value)) { return $Default }
    $v = $Value.Trim().ToLowerInvariant()
    if ($v -in @('1', 'true', 't', 'yes', 'y', 'on')) { return $true }
    if ($v -in @('0', 'false', 'f', 'no', 'n', 'off')) { return $false }
    return $Default
}

function Read-LineDefault {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $true)]
        [string]$Default
    )

    $raw = Read-Host ("{0} (Enter={1})" -f $Prompt, $Default)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    return $raw.Trim()
}

$scriptRoot = Get-ScriptRoot
$configPath = Ensure-SettingsFile -ScriptRoot $scriptRoot
$config = Read-ReferencePaths -ConfigPath $configPath

# Resolve INPUT_DIR / OUTPUT_DIR
$inputValue = Expand-ReferenceValue -Config $config -Value (Get-ConfigValue -Config $config -Key 'INPUT_DIR' -Default '01_images_input')
$outputValue = Expand-ReferenceValue -Config $config -Value (Get-ConfigValue -Config $config -Key 'OUTPUT_DIR' -Default '01_pdf_output')
$inputDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $inputValue
$outputDir = Resolve-ConfiguredPath -ScriptRoot $scriptRoot -Value $outputValue

# Defaults (configurable via tool_settings.txt / reference_paths.txt)
$defaultMethod = (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_DEFAULT_METHOD' -Default 'img2pdf')
$defaultMethod = $defaultMethod.Trim().ToLowerInvariant()
if ($defaultMethod -notin @('img2pdf','carrier')) { $defaultMethod = 'img2pdf' }

$defaultOverwrite = Parse-Bool -Value (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_OVERWRITE' -Default 'false') -Default $false
$defaultDpi = Parse-Int -Value (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_DPI' -Default '300') -Default 300
$defaultOptimize = (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_OPTIMIZE_MODE' -Default 'auto').Trim().ToLowerInvariant()
if ($defaultOptimize -notin @('lossless','auto','size')) { $defaultOptimize = 'auto' }
$defaultJpegQuality = Parse-Int -Value (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_JPEG_QUALITY' -Default '90') -Default 90
$defaultMaxLongEdge = Parse-Int -Value (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_MAX_LONG_EDGE' -Default '0') -Default 0
$defaultThresholdMb = Parse-Double -Value (Get-ConfigValue -Config $config -Key 'FOLDER2PDF_AUTO_REENCODE_THRESHOLD_MB' -Default '6.0') -Default 6.0

Write-Host ""
Write-Host "=== 画像フォルダ → PDF 生成 ==="
Write-Host ("設定ファイル: {0}" -f $configPath)
Write-Host ("INPUT_DIR : {0}" -f $inputDir)
Write-Host ("OUTPUT_DIR: {0}" -f $outputDir)
Write-Host ""
Write-Host ("デフォルト方式: {0}" -f $defaultMethod)
Write-Host ("デフォルト設定: overwrite={0}, dpi={1}, optimize={2}, jpeg_quality={3}, max_long_edge={4}, png_threshold_mb={5}" -f $defaultOverwrite, $defaultDpi, $defaultOptimize, $defaultJpegQuality, $defaultMaxLongEdge, $defaultThresholdMb)
Write-Host ""
Write-Host "Enterだけでデフォルト実行。設定を変えたい場合は以下を選択:"
Write-Host "  1) img2pdf方式で実行（デフォルト値）"
Write-Host "  2) Carrier方式で実行（テンプレPDF差し替え）"
Write-Host "  3) オプションを指定して実行"
Write-Host ""

$choice = ''
if (-not $RunDefault) {
    $choice = Read-Host "選択 (Enter=デフォルト実行, 1/2/3)"
    if ($null -eq $choice) { $choice = '' }
    $choice = $choice.Trim()
}

$method = $defaultMethod
$overwrite = $defaultOverwrite
$dpi = $defaultDpi
$optimize = $defaultOptimize
$jpegQuality = $defaultJpegQuality
$maxLongEdge = $defaultMaxLongEdge
$thresholdMb = $defaultThresholdMb

if ($choice -eq '1') {
    $method = 'img2pdf'
} elseif ($choice -eq '2') {
    $method = 'carrier'
} elseif ($choice -eq '3') {
    $method = Read-LineDefault -Prompt "方式 (img2pdf/carrier)" -Default $defaultMethod
    $method = $method.Trim().ToLowerInvariant()
    if ($method -notin @('img2pdf','carrier')) { $method = $defaultMethod }

    $overwriteRaw = Read-LineDefault -Prompt "上書きする？ (y/n)" -Default ($(if ($defaultOverwrite) { 'y' } else { 'n' }))
    $overwrite = Parse-Bool -Value $overwriteRaw -Default $defaultOverwrite

    if ($method -eq 'img2pdf') {
        $dpi = Parse-Int -Value (Read-LineDefault -Prompt "DPI（PDF上の物理サイズ計算用）" -Default ([string]$defaultDpi)) -Default $defaultDpi
        $optimize = Read-LineDefault -Prompt "optimize-mode (lossless/auto/size)" -Default $defaultOptimize
        $optimize = $optimize.Trim().ToLowerInvariant()
        if ($optimize -notin @('lossless','auto','size')) { $optimize = $defaultOptimize }
        $jpegQuality = Parse-Int -Value (Read-LineDefault -Prompt "JPEG quality (1-100)" -Default ([string]$defaultJpegQuality)) -Default $defaultJpegQuality
        $maxLongEdge = Parse-Int -Value (Read-LineDefault -Prompt "max-long-edge (px, 0=自動)" -Default ([string]$defaultMaxLongEdge)) -Default $defaultMaxLongEdge
        $thresholdMb = Parse-Double -Value (Read-LineDefault -Prompt "auto-reencode-threshold-mb (PNGのみ, auto時)" -Default ([string]$defaultThresholdMb)) -Default $defaultThresholdMb
    }
}

if ($method -eq 'carrier') {
    Write-Host ""
    Write-Host "[INFO] Carrier方式で実行します。BASE_PDF_PATH が tool_settings.txt（または reference_paths.txt）に必要です。"
    $py = Join-Path $scriptRoot 'src\\folder2pdf_carrier.py'
    if (-not (Test-Path -LiteralPath $py)) {
        Write-Error ("folder2pdf_carrier.py が見つかりません: {0}" -f $py)
        exit 1
    }

    & python $py
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[INFO] img2pdf方式で実行します。"
$py = Join-Path $scriptRoot 'src\\folder2pdf.py'
if (-not (Test-Path -LiteralPath $py)) {
    Write-Error ("folder2pdf.py が見つかりません: {0}" -f $py)
    exit 1
}

$argsList = @(
    $inputDir,
    $outputDir,
    '--dpi', [string]$dpi,
    '--optimize-mode', [string]$optimize,
    '--jpeg-quality', [string]$jpegQuality,
    '--max-long-edge', [string]$maxLongEdge,
    '--auto-reencode-threshold-mb', [string]$thresholdMb
)
if ($overwrite) { $argsList += '--overwrite' }

& python $py @argsList
exit $LASTEXITCODE

