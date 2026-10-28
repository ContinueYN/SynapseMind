param(
    [string]$Docx = (Join-Path $PSScriptRoot "..\docs\design\release\SynapseMind-单题诊断引导-设计方案.docx"),
    [string]$Pdf  = (Join-Path $PSScriptRoot "..\docs\design\release\SynapseMind-单题诊断引导-设计方案.pdf")
)

$ErrorActionPreference = "Stop"

$Docx = (Resolve-Path -LiteralPath $Docx).Path
$PdfDir = Split-Path -Parent $Pdf
if (-not (Test-Path -LiteralPath $PdfDir)) {
    New-Item -ItemType Directory -Force -Path $PdfDir | Out-Null
}

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0

    $doc = $word.Documents.Open($Docx, $false, $false, $false)
    $doc.Repaginate()
    $doc.Fields.Update() | Out-Null

    if ($doc.TablesOfContents.Count -gt 0) {
        $doc.TablesOfContents.Item(1).Update() | Out-Null
    }
    $doc.Repaginate()

    if ($doc.TablesOfContents.Count -gt 0) {
        $toc = $doc.TablesOfContents.Item(1)
        foreach ($p in $toc.Range.Paragraphs) {
            if ($p.Style.NameLocal -eq "TOC 1") {
                $p.Range.Font.Color = 6515471
                $p.Range.Font.Bold = $true
                $p.Range.Font.Size = 10.5
            } else {
                $p.Range.Font.Color = 7367517
                $p.Range.Font.Bold = $false
                $p.Range.Font.Size = 9.5
            }
        }
    }

    $doc.Repaginate()
    $pages = $doc.ComputeStatistics(2)
    $doc.Save()

    $doc.ExportAsFixedFormat(
        $Pdf, 17, $false, 0, 0, 0, 0, 0,
        $true, $true, 1, $true, $true, $false
    ) | Out-Null

    Write-Host "DOCX: $Docx"
    Write-Host "PDF : $Pdf"
    Write-Host "Pages: $pages"
}
finally {
    if ($null -ne $doc) {
        $doc.Close($false) | Out-Null
    }
    if ($null -ne $word) {
        $word.Quit() | Out-Null
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}