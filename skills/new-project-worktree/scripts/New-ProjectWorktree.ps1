#Requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('(?-i)\A[a-z][a-z0-9]*\z')][string]$Type,
    [Parameter(Mandatory)][ValidatePattern('(?-i)\A[a-z0-9]+(?:-[a-z0-9]+)*\z')][string]$Name,
    [ValidateNotNullOrEmpty()][string]$Base = 'develop',
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$git = (Get-Command git -CommandType Application | Select-Object -First 1).Source
if ((Get-Location).Provider.Name -ne 'FileSystem') { throw '請從 Git 工作目錄執行。' }

foreach ($variable in 'GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_NAMESPACE','GIT_QUARANTINE_PATH') {
    if ([Environment]::GetEnvironmentVariable($variable)) {
        throw "Git 環境變數 $variable 會變更工作位置。請改用一般 Git 工作目錄執行。"
    }
}

function Invoke-Git([string]$Directory, [string[]]$Arguments) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $git
    $info.WorkingDirectory = $Directory
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.UTF8Encoding]::new($false, $true)
    $info.ArgumentList.Add('-c')
    $info.ArgumentList.Add('core.hooksPath=/dev/null')
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }

    $process = [Diagnostics.Process]::Start($info)
    try {
        $output = $process.StandardOutput.ReadToEndAsync()
        $diagnostics = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $message = $diagnostics.GetAwaiter().GetResult().Trim()
        if ($process.ExitCode -ne 0) { throw "Git 失敗（$($process.ExitCode)）：$message" }
        return $output.GetAwaiter().GetResult()
    } finally {
        $process.Dispose()
    }
}

function Get-WorktreeRecords([string]$Directory) {
    $output = Invoke-Git $Directory @('worktree','list','--porcelain','-z')
    foreach ($record in $output.Split([string]::new([char]0, 2), [StringSplitOptions]::RemoveEmptyEntries)) {
        $fields = $record.Split([char]0)
        if (!$fields[0].StartsWith('worktree ', [StringComparison]::Ordinal)) { throw '無法辨識 Git 工作樹清單。' }
        [pscustomobject]@{
            Path = [IO.Path]::GetFullPath($fields[0].Substring(9))
            Bare = $fields -ccontains 'bare'
            Fields = $fields
        }
    }
}

function Get-GitCommonDirectory([string]$Directory) {
    $output = Invoke-Git $Directory @('rev-parse','--path-format=absolute','--git-common-dir')
    [IO.Path]::GetFullPath($output.TrimEnd([char[]]@(13,10)))
}

function Assert-DirectDirectory([string]$Path) {
    $current = Get-Item -LiteralPath $Path -Force
    while ($null -ne $current) {
        if ($current -isnot [IO.DirectoryInfo] -or $current.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
            throw "請使用未經符號連結或 junction 重導的實體目錄：$($current.FullName)"
        }
        $current = $current.Parent
    }
}

$cwd = (Get-Location).ProviderPath
$worktrees = @(Get-WorktreeRecords $cwd)
if (!$worktrees.Count -or $worktrees[0].Bare) { throw '需要具備主要 checkout 的 Git 專案。' }
$main = $worktrees[0].Path
Assert-DirectDirectory $main

$pathComparison = if ($IsWindows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
if (![string]::Equals((Get-GitCommonDirectory $cwd), (Get-GitCommonDirectory $main), $pathComparison)) {
    throw '目前目錄與主要 checkout 的 Git 資料不相符。'
}
$mainTop = (Invoke-Git $main @('rev-parse','--show-toplevel')).TrimEnd([char[]]@(13,10))
if (![string]::Equals([IO.Path]::GetFullPath($mainTop), $main, $pathComparison)) { throw '無法確認主要 checkout 的根目錄。' }
if ([IO.Path]::GetFileName($main) -ine 'repo') { throw "主要 checkout 應位於專案的 repo/ 目錄：$main" }

$parent = [IO.Path]::GetDirectoryName($main)
$destinationRoot = Join-Path $parent 'worktrees'
$leaf = "$Type-$Name"
$destination = Join-Path $destinationRoot $leaf
$branch = "codex/$Type/$Name"
$branchRef = "refs/heads/$branch"
$baseRef = "refs/heads/$Base"
$null = Invoke-Git $main @('check-ref-format', $branchRef)
$null = Invoke-Git $main @('check-ref-format', $baseRef)
$commit = (Invoke-Git $main @('rev-parse','--verify','--end-of-options',"$baseRef^{commit}")).Trim()
if ($commit -cnotmatch '\A(?:[a-f0-9]{40}|[a-f0-9]{64})\z') { throw '無法核對基線 commit。' }

$refs = (Invoke-Git $main @('for-each-ref','--format=%(refname)','refs/heads')).Split([char]10)
foreach ($refLine in $refs) {
    $ref = $refLine.TrimEnd([char]13)
    if ($ref -ieq $branchRef -or $ref.StartsWith("$branchRef/", [StringComparison]::OrdinalIgnoreCase) -or
        ($ref -and $branchRef.StartsWith("$ref/", [StringComparison]::OrdinalIgnoreCase))) {
        throw "分支名稱已占用：$ref"
    }
}
foreach ($entry in $worktrees) {
    if ([string]::Equals($entry.Path, $destination, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Git 已登記該工作樹：$destination"
    }
}

$containers = @(Get-ChildItem -LiteralPath $parent -Force | Where-Object Name -ieq 'worktrees')
if ($containers.Count -gt 1 -or ($containers.Count -eq 1 -and $containers[0].Name -cne 'worktrees')) {
    throw "worktrees 目錄名稱有大小寫衝突：$parent"
}
if ($containers.Count -eq 1) {
    Assert-DirectDirectory $destinationRoot
    if (Get-ChildItem -LiteralPath $destinationRoot -Force | Where-Object Name -ieq $leaf) {
        throw "目的地已存在：$destination"
    }
}

if ($Apply) {
    try {
        $null = Invoke-Git $main @('worktree','add','-b',$branch,'--',$destination,$commit)
        $created = @(Get-WorktreeRecords $main | Where-Object {
            [string]::Equals($_.Path, $destination, $pathComparison)
        })
        if ($created.Count -ne 1 -or $created[0].Fields -cnotcontains "branch $branchRef" -or
            $created[0].Fields -cnotcontains "HEAD $commit") {
            throw '建立後的工作樹、分支或 HEAD 與預覽不符。'
        }
    } catch {
        throw "建立未完成。請核對目的地 $destination 和分支 $branch 後再重試。$($_.Exception.Message)"
    }
}
[pscustomobject]@{
    Status = if ($Apply) { 'Created' } else { 'Preview' }
    MainRepository = $main
    Worktree = $destination
    Branch = $branch
    Base = $Base
    Commit = $commit
}
