param([string[]]$InputPaths)
$ErrorActionPreference = 'Stop'
$taskWorkspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$app = $null
try {
    foreach ($inputPath in $InputPaths) {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $absoluteInput = [System.IO.Path]::GetFullPath($inputPath)
        if (-not $absoluteInput.StartsWith($taskWorkspace + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Input is outside the design workspace' }
        $renderDir = Join-Path $PSScriptRoot ('render_' + [System.IO.Path]::GetFileNameWithoutExtension($absoluteInput))
        New-Item -ItemType Directory -Force -Path $renderDir | Out-Null
        $pdfPath = Join-Path $renderDir ([System.IO.Path]::GetFileNameWithoutExtension($absoluteInput) + '.pdf')
        $document = $app.Documents.Open($absoluteInput, $false, $true)
        try {
            $document.ExportAsFixedFormat($pdfPath, 17)
            Write-Output $pdfPath
        } finally { $document.Close(0) }
        try { $app.Quit() } catch { Write-Output 'Conversion application has already exited' }
        $app=$null
    }
} finally {
    if ($null -ne $app) { try { $app.Quit() } catch { Write-Output 'Conversion application has already exited' } }
}
