$ErrorActionPreference = 'Stop'

$pattern = '(?ms)^```powershell[ \t]*\r?\n(.*?)^```[ \t]*$'
$files = @(& git ls-files -- '*.md' | Where-Object {
    $_ -notlike 'docs/upstream/*' -and
    $_ -notlike 'docs/security/reports/*' -and
    $_ -notlike 'bench/quarantine/*'
})
$count = 0
$problems = [System.Collections.Generic.List[string]]::new()

foreach ($path in $files) {
    $markdown = [System.IO.File]::ReadAllText((Join-Path (Get-Location) $path))
    foreach ($match in [regex]::Matches($markdown, $pattern)) {
        $count++
        $tokens = $null
        $parseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseInput(
            $match.Groups[1].Value,
            [ref]$tokens,
            [ref]$parseErrors
        )
        foreach ($parseError in $parseErrors) {
            $problems.Add("${path}: PowerShell parse error: $($parseError.Message)")
        }
    }
}

if ($problems.Count -gt 0) {
    $problems | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output "Parsed $count documented PowerShell code blocks."
