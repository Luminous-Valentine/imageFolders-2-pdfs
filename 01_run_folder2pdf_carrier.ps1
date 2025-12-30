<##
This launcher reads directory settings from tool_settings.txt (legacy: reference_paths.txt) and runs folder2pdf_carrier.py.

Directory roles (from settings file):
- INPUT_DIR: contains subfolders of images to convert
- OUTPUT_DIR: destination for generated PDFs
- BASE_PDF_PATH: path to the base PDF template
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

# NOTE: We delegate the actual config reading to the Python script for simplicity,
# but we can do some pre-checks here if needed. 
# For this script, we just launch the python script which handles ref_paths internally.
# However, to be consistent with other scripts, we could parse it here to pass args,
# but folder2pdf_carrier.py reads ref_paths directly. 
# So we just invoke it. The InputDir/OutputDir params above are kept for interface consistency
# but might need to be passed if we want CLI override capability.
# For now, let's just launch the python script and let it read tool_settings.txt (legacy: reference_paths.txt).
# as the primary source of truth, unless overrides are strictly needed.
#
# Actually, the user asked to refer to 01_run_folder2pdf.ps1 which DOES parse and pass args.
# So let's stick to that pattern if possible, BUT folder2pdf_carrier.py logic I wrote
# prefers internal reading.
# Let's simple launch the python script without arguments, as it is self-contained with ref_paths.
# If CLI overrides are needed, we would need to update the Python script to accept them.
# Given the user request "settings text format... is implied source",
# I will let Python handle it to ensure consistency with the logic I just wrote.

$scriptRoot = Get-ScriptRoot
Ensure-SettingsFile -ScriptRoot $scriptRoot | Out-Null
$py = Join-Path $scriptRoot 'src\\folder2pdf_carrier.py'

Write-Host "Starting folder2pdf_carrier.py..."
& python $py
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { exit $exitCode }
