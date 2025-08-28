param(
  [string]$Input = "$PSScriptRoot/../docs/diagram.mmd",
  [string]$Output = "$PSScriptRoot/../docs/diagram.png"
)

Write-Host "Exporting Mermaid diagram:" -ForegroundColor Cyan
Write-Host "  Input : $Input"
Write-Host "  Output: $Output"

# Use npx to avoid global install
$npx = "npx"
$pkg = "@mermaid-js/mermaid-cli"

$cmd = "$npx -y $pkg -i `"$Input`" -o `"$Output`""
Write-Host "> $cmd"
Invoke-Expression $cmd
