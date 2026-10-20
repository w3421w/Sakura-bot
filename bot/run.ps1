$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.\config.json')) {
    Copy-Item -LiteralPath '.\config.example.json' -Destination '.\config.json'
    Write-Host 'Created config.json from config.example.json. Review group IDs, token and consent before starting.'
}
python .\app.py --config .\config.json
