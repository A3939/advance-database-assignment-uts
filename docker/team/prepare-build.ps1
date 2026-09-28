#Requires -Version 5.1
# Export Git commit/tree objects without requiring Python on the host.
$ErrorActionPreference = 'Stop'
$gitPath = (Get-Command git -CommandType Application -ErrorAction Stop).Source

function Invoke-GitText {
    param([string[]]$GitArguments)
    $result = @(& $gitPath @GitArguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Git failed during build preparation (exit $LASTEXITCODE)."
    }
    return $result
}

$repoRoot = [string](Invoke-GitText -GitArguments @('rev-parse', '--show-toplevel'))
$proofDir = Join-Path $repoRoot 'artifacts/team'
$proofPath = Join-Path $proofDir 'build-provenance.objects'
[System.IO.Directory]::CreateDirectory($proofDir) | Out-Null
# Remove stale proof even when the checkout or HEAD check below fails.
if (Test-Path -LiteralPath $proofPath) {
    Remove-Item -LiteralPath $proofPath -Force
}

$objectFormat = Invoke-GitText -GitArguments @('-C', $repoRoot, 'rev-parse', '--show-object-format')
if ($objectFormat -ne 'sha1') {
    throw 'This build requires a SHA-1 Git repository.'
}
$head = [string](Invoke-GitText -GitArguments @('--no-replace-objects', '-C', $repoRoot, 'rev-parse', '--verify', 'HEAD^{commit}'))
if ($head -cnotmatch '^[0-9a-f]{40}$') {
    throw 'HEAD must be a full 40-character Git commit SHA.'
}

function Assert-CleanTrackedFiles {
    & $gitPath -C $repoRoot diff --quiet $head --
    if ($LASTEXITCODE -ne 0) {
        throw 'Commit or restore tracked changes, then prepare again. No build proof was kept.'
    }
}
Assert-CleanTrackedFiles

$tempDir = Join-Path $proofDir ('.prepare-build.' + [System.Guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tempDir) | Out-Null
try {
    $rootTree = [string](Invoke-GitText -GitArguments @('--no-replace-objects', '-C', $repoRoot, 'rev-parse', ($head + '^{tree}')))
    $treeRows = @(Invoke-GitText -GitArguments @('--no-replace-objects', '-C', $repoRoot, 'ls-tree', '-r', '-t', '--format=%(objecttype) %(objectname)', $head))
    $objectIds = [System.Collections.Generic.List[string]]::new()
    $treeIds = [System.Collections.Generic.HashSet[string]]::new()
    $objectIds.Add($head)
    $objectIds.Add($rootTree)
    $treeIds.Add($rootTree) | Out-Null
    foreach ($row in $treeRows) {
        if ($row -cmatch '^tree ([0-9a-f]{40})$' -and $treeIds.Add($Matches[1])) {
            $objectIds.Add($Matches[1])
        }
    }

    $tempProof = Join-Path $tempDir 'proof'
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo.FileName = $gitPath
    $process.StartInfo.Arguments = '--no-replace-objects cat-file --batch'
    $process.StartInfo.WorkingDirectory = $repoRoot
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardInput = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $stream = [System.IO.File]::Open($tempProof, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $started = $false
    try {
        $started = $process.Start()
        if (!$started) { throw 'Could not start git cat-file.' }
        # Copy bytes directly: PowerShell text redirection corrupts tree NULs.
        # Drain stdout and stderr while writing stdin to avoid pipe deadlocks.
        $copyTask = $process.StandardOutput.BaseStream.CopyToAsync($stream)
        $errorTask = $process.StandardError.ReadToEndAsync()
        foreach ($objectId in $objectIds) {
            $process.StandardInput.WriteLine($objectId)
        }
        $process.StandardInput.Close()
        $copyTask.GetAwaiter().GetResult()
        $process.WaitForExit()
        $gitError = $errorTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {
            throw "git cat-file failed (exit $($process.ExitCode)): $gitError"
        }
    }
    finally {
        if ($started -and !$process.HasExited) { $process.Kill() }
        $stream.Dispose()
        $process.Dispose()
    }

    $currentHead = [string](Invoke-GitText -GitArguments @('--no-replace-objects', '-C', $repoRoot, 'rev-parse', '--verify', 'HEAD'))
    if ($currentHead -cne $head) {
        throw 'HEAD changed during preparation. Run this script again.'
    }
    Assert-CleanTrackedFiles
    [System.IO.File]::Move($tempProof, $proofPath)
}
finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force
}

Write-Host "Prepared build proof for Git commit $head."
Write-Host "Set ARSIA_REVISION in .env to $head."
Write-Host 'Next: docker compose --profile tools build app'
