param(
  [string]$TdxRoot = "D:\APP_SOFT\TDX",
  [string]$OutputDir = "python-bridge\research\out"
)

$ErrorActionPreference = "Stop"

function Ensure-Directory {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function Convert-BytesToAsciiStrings {
  param(
    [byte[]]$Bytes,
    [int]$MinLength = 5
  )

  $strings = New-Object System.Collections.Generic.List[string]
  $buffer = New-Object System.Text.StringBuilder

  foreach ($byte in $Bytes) {
    if ($byte -ge 32 -and $byte -le 126) {
      [void]$buffer.Append([char]$byte)
      continue
    }

    if ($buffer.Length -ge $MinLength) {
      $strings.Add($buffer.ToString())
    }
    [void]$buffer.Clear()
  }

  if ($buffer.Length -ge $MinLength) {
    $strings.Add($buffer.ToString())
  }

  return $strings
}

function Convert-BytesToUnicodeStrings {
  param(
    [byte[]]$Bytes,
    [int]$MinLength = 5
  )

  $strings = New-Object System.Collections.Generic.List[string]
  $buffer = New-Object System.Text.StringBuilder

  for ($index = 0; $index -lt ($Bytes.Length - 1); $index += 2) {
    $lo = $Bytes[$index]
    $hi = $Bytes[$index + 1]
    if ($hi -eq 0 -and $lo -ge 32 -and $lo -le 126) {
      [void]$buffer.Append([char]$lo)
      continue
    }

    if ($buffer.Length -ge $MinLength) {
      $strings.Add($buffer.ToString())
    }
    [void]$buffer.Clear()
  }

  if ($buffer.Length -ge $MinLength) {
    $strings.Add($buffer.ToString())
  }

  return $strings
}

function Read-UInt16 {
  param([byte[]]$Bytes, [int]$Offset)
  return [BitConverter]::ToUInt16($Bytes, $Offset)
}

function Read-UInt32 {
  param([byte[]]$Bytes, [int]$Offset)
  return [BitConverter]::ToUInt32($Bytes, $Offset)
}

function Read-AsciiZ {
  param([byte[]]$Bytes, [int]$Offset)
  $items = New-Object System.Collections.Generic.List[byte]
  for ($index = $Offset; $index -lt $Bytes.Length -and $Bytes[$index] -ne 0; $index++) {
    $items.Add($Bytes[$index])
  }
  return [System.Text.Encoding]::ASCII.GetString($items.ToArray())
}

function Convert-RvaToOffset {
  param(
    [uint32]$Rva,
    [array]$Sections
  )

  foreach ($section in $Sections) {
    $size = [Math]::Max([uint32]$section.VirtualSize, [uint32]$section.SizeOfRawData)
    if ($Rva -ge $section.VirtualAddress -and $Rva -lt ($section.VirtualAddress + $size)) {
      return [int]($section.PointerToRawData + ($Rva - $section.VirtualAddress))
    }
  }

  return -1
}

function Get-PeExports {
  param([string]$Path)

  $bytes = [System.IO.File]::ReadAllBytes($Path)
  if ($bytes.Length -lt 0x100) { return @() }

  $peOffset = [int](Read-UInt32 $bytes 0x3C)
  if ($peOffset -lt 0 -or ($peOffset + 0x18) -ge $bytes.Length) { return @() }

  $optionalHeaderOffset = $peOffset + 0x18
  $optionalMagic = Read-UInt16 $bytes $optionalHeaderOffset
  $isPe32Plus = $optionalMagic -eq 0x20b
  $dataDirectoryOffset = $optionalHeaderOffset + ($(if ($isPe32Plus) { 0x70 } else { 0x60 }))
  $exportRva = Read-UInt32 $bytes $dataDirectoryOffset
  if ($exportRva -eq 0) { return @() }

  $numberOfSections = Read-UInt16 $bytes ($peOffset + 0x6)
  $sizeOfOptionalHeader = Read-UInt16 $bytes ($peOffset + 0x14)
  $sectionOffset = $optionalHeaderOffset + $sizeOfOptionalHeader
  $sections = @()

  for ($index = 0; $index -lt $numberOfSections; $index++) {
    $offset = $sectionOffset + ($index * 40)
    if (($offset + 40) -gt $bytes.Length) { break }
    $sections += [pscustomobject]@{
      Name = Read-AsciiZ $bytes $offset
      VirtualSize = Read-UInt32 $bytes ($offset + 8)
      VirtualAddress = Read-UInt32 $bytes ($offset + 12)
      SizeOfRawData = Read-UInt32 $bytes ($offset + 16)
      PointerToRawData = Read-UInt32 $bytes ($offset + 20)
    }
  }

  $exportOffset = Convert-RvaToOffset $exportRva $sections
  if ($exportOffset -lt 0 -or ($exportOffset + 40) -gt $bytes.Length) { return @() }

  $numberOfNames = Read-UInt32 $bytes ($exportOffset + 24)
  $addressOfNamesRva = Read-UInt32 $bytes ($exportOffset + 32)
  $namesOffset = Convert-RvaToOffset $addressOfNamesRva $sections
  if ($namesOffset -lt 0) { return @() }

  $exports = New-Object System.Collections.Generic.List[string]
  for ($index = 0; $index -lt $numberOfNames; $index++) {
    $nameRva = Read-UInt32 $bytes ($namesOffset + ($index * 4))
    $nameOffset = Convert-RvaToOffset $nameRva $sections
    if ($nameOffset -ge 0 -and $nameOffset -lt $bytes.Length) {
      $exports.Add((Read-AsciiZ $bytes $nameOffset))
    }
  }

  return $exports
}

Ensure-Directory -Path $OutputDir

$targets = @(
  (Join-Path $TdxRoot "tdxw.exe"),
  (Join-Path $TdxRoot "TdxW.exe"),
  (Join-Path $TdxRoot "TDXDeep.dll"),
  (Join-Path $TdxRoot "nacomte.dat"),
  (Join-Path $TdxRoot "nbcomte.dat")
)

$keywords = @(
  "7719",
  "L2",
  "L2HOST",
  "SDKL2Agent",
  "QSTP",
  "QSTPLevel2",
  "TdxDeep",
  "TdxDeep_StartInit",
  "TdxDeep_Data",
  "TdxDeep_Uninit",
  "NoSDKUseQSTPCheckL2",
  "SepcComte",
  "comte",
  "auth",
  "login",
  "token",
  "password"
)

$report = [ordered]@{
  generatedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  tdxRoot = $TdxRoot
  files = @()
}

foreach ($target in $targets) {
  if (-not (Test-Path -LiteralPath $target)) {
    $report.files += [ordered]@{
      path = $target
      exists = $false
    }
    continue
  }

  $bytes = [System.IO.File]::ReadAllBytes($target)
  $asciiStrings = Convert-BytesToAsciiStrings -Bytes $bytes -MinLength 5
  $unicodeStrings = Convert-BytesToUnicodeStrings -Bytes $bytes -MinLength 5
  $allStrings = @($asciiStrings + $unicodeStrings | Sort-Object -Unique)
  $matches = foreach ($keyword in $keywords) {
    $matched = @($allStrings | Where-Object { $_ -like "*$keyword*" } | Select-Object -First 100)
    if ($matched.Count -gt 0) {
      [ordered]@{
        keyword = $keyword
        count = $matched.Count
        samples = $matched
      }
    }
  }

  $exports = @()
  if ($target.ToLowerInvariant().EndsWith(".dll") -or $target.ToLowerInvariant().EndsWith(".exe")) {
    try {
      $exports = @(Get-PeExports -Path $target)
    } catch {
      $exports = @("EXPORT_PARSE_FAILED: $($_.Exception.Message)")
    }
  }

  $fileReport = [ordered]@{
    path = $target
    exists = $true
    length = $bytes.Length
    lastWriteTime = (Get-Item -LiteralPath $target).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    exportCount = $exports.Count
    exports = $exports
    keywordMatches = @($matches)
  }

  $report.files += $fileReport

  $baseName = [System.IO.Path]::GetFileName($target)
  $allStrings | Set-Content -Path (Join-Path $OutputDir "$baseName.strings.txt") -Encoding UTF8
}

$jsonPath = Join-Path $OutputDir "tdx_l2_artifacts_report.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonPath -Encoding UTF8
Write-Output $jsonPath
