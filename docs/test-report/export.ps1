# Opens the built report in Word, fills the table of contents and every field (company, page
# numbers, year), then saves it and a PDF beside it. Windows with Word installed.
#   powershell -File docs/test-report/export.ps1 docs/test-report/Lanka-Link-v3-Master-Test-Plan.docx
param([Parameter(Mandatory = $true)][string]$Path)
$full = (Resolve-Path $Path).Path
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
  $doc = $word.Documents.Open($full)
  foreach ($story in $doc.StoryRanges) {
    $s = $story
    while ($s -ne $null) { [void]$s.Fields.Update(); $s = $s.NextStoryRange }
  }
  foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
  $doc.Save()
  $doc.SaveAs2([IO.Path]::ChangeExtension($full, ".pdf"), 17)  # 17 = wdFormatPDF
  $doc.Close()
} finally {
  $word.Quit()
}
