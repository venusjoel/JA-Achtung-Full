[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

if (-not $SkipBuild) {
    & "$PSScriptRoot\build.ps1"
}

$sof = Join-Path $PSScriptRoot 'output_files\de10_game.sof'
if (-not (Test-Path -LiteralPath $sof)) {
    throw "Bitstream not found at $sof. Run .\build.ps1 first."
}

$command = Get-Command quartus_pgm -ErrorAction SilentlyContinue
if ($command) {
    $quartusPgm = $command.Source
} else {
    $candidates = @()
    if ($env:QUARTUS_ROOTDIR) {
        $candidates += Join-Path $env:QUARTUS_ROOTDIR 'bin64\quartus_pgm.exe'
        $candidates += Join-Path $env:QUARTUS_ROOTDIR 'bin\quartus_pgm.exe'
    }
    $candidates += 'C:\intelFPGA_lite\17.0\quartus\bin64\quartus_pgm.exe'
    $candidates += 'C:\intelFPGA_lite\17.0\quartus\bin\quartus_pgm.exe'
    $quartusPgm = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $quartusPgm) {
    throw 'quartus_pgm was not found. Install Quartus Prime Lite or add its bin64 directory to PATH.'
}

$workRoot = if ($env:JA_ACHTUNG_FPGA_WORK) { $env:JA_ACHTUNG_FPGA_WORK } else { 'C:\fpga_work' }
$programRoot = Join-Path $workRoot ("repo_program_" + [guid]::NewGuid().ToString('N').Substring(0, 8))
try {
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $programRoot -Force | Out-Null
    Copy-Item -LiteralPath $sof -Destination (Join-Path $programRoot 'de10_game.sof')

    Push-Location $programRoot
    try {
        & $quartusPgm -m jtag -o 'p;de10_game.sof'
        if ($LASTEXITCODE -ne 0) {
            throw "FPGA programming failed with exit code $LASTEXITCODE. Check the DE10-Lite USB-Blaster connection."
        }
    } finally {
        Pop-Location
    }
} finally {
    if (Test-Path -LiteralPath $programRoot) {
        $tempRoot = [System.IO.Path]::GetFullPath($workRoot).TrimEnd('\')
        $programFull = [System.IO.Path]::GetFullPath($programRoot)
        if ($programFull.StartsWith($tempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $programFull -Recurse -Force
        } else {
            Write-Warning "Refusing to remove unexpected programming path: $programFull"
        }
    }
}

Write-Host 'DE10-Lite programmed successfully. Hold KEY0 briefly, then release it to reset the game and PSRAM.'
