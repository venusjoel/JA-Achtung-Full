[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Find-QuartusTool {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @()
    if ($env:QUARTUS_ROOTDIR) {
        $candidates += Join-Path $env:QUARTUS_ROOTDIR "bin64\$Name.exe"
        $candidates += Join-Path $env:QUARTUS_ROOTDIR "bin\$Name.exe"
    }
    $candidates += "C:\intelFPGA_lite\17.0\quartus\bin64\$Name.exe"
    $candidates += "C:\intelFPGA_lite\17.0\quartus\bin\$Name.exe"

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "$Name was not found. Install Quartus Prime Lite with MAX 10 support or add its bin64 directory to PATH."
}

$quartusSh = Find-QuartusTool -Name 'quartus_sh'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workRoot = if ($env:JA_ACHTUNG_FPGA_WORK) { $env:JA_ACHTUNG_FPGA_WORK } else { 'C:\fpga_work' }
$stageRoot = Join-Path $workRoot ("repo_build_" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$stageProject = Join-Path $stageRoot 'fpga\de10_lite'
$stageSrc = Join-Path $stageRoot 'src'
$repoOutput = Join-Path $PSScriptRoot 'output_files'

try {
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stageProject -Force | Out-Null
    New-Item -ItemType Directory -Path $stageSrc -Force | Out-Null

    foreach ($name in @('de10_fpga_top.v', 'de10_game.qpf', 'de10_game.qsf', 'de10_game.sdc')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $stageProject
    }
    Copy-Item -Path (Join-Path $repoRoot 'src\*') -Destination $stageSrc -Force

    Push-Location $stageProject
    try {
        & $quartusSh --flow compile de10_game
        if ($LASTEXITCODE -ne 0) {
            throw "Quartus compilation failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }

    $stageSof = Join-Path $stageProject 'output_files\de10_game.sof'
    if (-not (Test-Path -LiteralPath $stageSof)) {
        throw "Quartus reported success but did not create $stageSof."
    }
    New-Item -ItemType Directory -Path $repoOutput -Force | Out-Null
    Copy-Item -LiteralPath $stageSof -Destination (Join-Path $repoOutput 'de10_game.sof') -Force
} finally {
    if (Test-Path -LiteralPath $stageRoot) {
        $tempRoot = [System.IO.Path]::GetFullPath($workRoot).TrimEnd('\')
        $stageFull = [System.IO.Path]::GetFullPath($stageRoot)
        if ($stageFull.StartsWith($tempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $stageFull -Recurse -Force
        } else {
            Write-Warning "Refusing to remove unexpected staging path: $stageFull"
        }
    }
}

Write-Host "Built from this repository's src/: $repoOutput\de10_game.sof"
