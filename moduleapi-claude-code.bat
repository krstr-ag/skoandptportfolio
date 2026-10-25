@echo off
setlocal DisableDelayedExpansion
if not defined SystemRoot set "SystemRoot=C:\Windows"
set "PATH=%SystemRoot%\System32;%SystemRoot%\System32\WindowsPowerShell\v1.0;%PATH%"
chcp 65001 >nul
set "MODULE_CLAUDE_SETUP_FILE=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$s=[IO.File]::ReadAllText($env:MODULE_CLAUDE_SETUP_FILE,[Text.Encoding]::UTF8); & ([scriptblock]::Create(($s -split '(?m)^# MODULEAPI_POWERSHELL\r?$',2)[1]))"
set "MODULE_SETUP_EXIT=%errorlevel%"
echo.
pause
exit /b %MODULE_SETUP_EXIT%
# MODULEAPI_POWERSHELL
param([switch]$FunctionsOnly)

$ErrorActionPreference = 'Stop'
$ModuleBaseUrl = 'https://moduleapi.pro'
# The modelPicker setting, which puts every ModuleAPI model into /model, needs this Claude Code version.
$PickerMinimumVersion = [version]'2.1.242'

function Get-ClaudeConfigRoot {
    $root = [Environment]::GetEnvironmentVariable('CLAUDE_CONFIG_DIR', 'Process')
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.claude' }
    if (-not [IO.Path]::IsPathRooted($root)) { throw 'CLAUDE_CONFIG_DIR должен содержать абсолютный путь.' }
    return [IO.Path]::GetFullPath($root)
}

function Read-ClaudeSettings([string]$ConfigRoot) {
    $file = Join-Path $ConfigRoot 'settings.json'
    $exists = Test-Path -LiteralPath $file
    $original = if ($exists) { [IO.File]::ReadAllText($file, [Text.Encoding]::UTF8) } else { '{}' }
    $text = if ([string]::IsNullOrWhiteSpace($original)) { '{}' } else { $original }
    try { $settings = ConvertFrom-Json -InputObject $text }
    catch { throw ('settings.json содержит некорректный JSON: ' + $file + ' (' + $_.Exception.Message + '). Настройки не изменены.') }
    if ($settings -isnot [PSCustomObject]) { throw 'settings.json должен содержать JSON-объект. Настройки не изменены.' }
    if ($null -eq $settings.env) { $settings | Add-Member -MemberType NoteProperty -Name env -Value ([PSCustomObject]@{}) -Force }
    if ($settings.env -isnot [PSCustomObject]) { throw 'Поле env в settings.json должно быть JSON-объектом. Настройки не изменены.' }
    return @{ File = $file; Exists = $exists; Original = $original; Settings = $settings; Json = (ConvertTo-Json -InputObject $settings -Depth 100) }
}

# Key from a previous run of this setup, otherwise the one the Codex Desktop setup saved in MODULE_API_KEY.
function Get-SavedModuleKey($Settings, [string]$CodexKey) {
    $token = [string]$Settings.env.ANTHROPIC_AUTH_TOKEN
    if ($token -match '^sk-' -and [string]$Settings.env.ANTHROPIC_BASE_URL -match '^https://(api\.)?moduleapi\.pro/?$') { return $token.Trim() }
    if ($CodexKey -match '^\s*sk-') { return $CodexKey.Trim() }
    return $null
}

# Returns the models the key may use, or $null when ModuleAPI rejects the key.
function Get-ModuleModels([string]$ApiKey) {
    if ($ApiKey -notmatch '^sk-[A-Za-z0-9_-]{10,}$') { throw 'Вставьте полный ключ ModuleAPI, начинающийся с sk-, без кавычек и Bearer.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($ModuleBaseUrl + '/v1/models') -Headers @{ Authorization = ('Bearer ' + $ApiKey) } -TimeoutSec 20 -MaximumRedirection 0
        $capability = Invoke-WebRequest -UseBasicParsing -Method Options -Uri ($ModuleBaseUrl + '/v1/messages') -TimeoutSec 20 -MaximumRedirection 0
    } catch [Net.WebException] {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        if ($status -eq 401 -or $status -eq 403) { return $null }
        throw "Проверка ModuleAPI не прошла (HTTP $status). Проверьте интернет и повторите запуск. Настройки не изменены."
    }
    if ($capability.Headers['x-moduleapi-messages'] -ne '1') { throw 'Сервер не подтвердил поддержку Claude Code. Обратитесь в поддержку ModuleAPI.' }
    # Image-generation models cannot answer Claude Code's text requests.
    $models = @((ConvertFrom-Json -InputObject $response.Content).data | Where-Object { $_.id -and $_.id -notmatch 'image' })
    if (-not $models.Count) { throw 'Ключу не разрешена ни одна текстовая модель. Разрешите модели в личном кабинете → «Ключи API».' }
    return ,$models
}

function Select-ModuleModel([string[]]$Ids, [string[]]$Candidates, [string]$Fallback) {
    foreach ($id in $Candidates) { if ($id -and $Ids -contains $id) { return $id } }
    return $Fallback
}

function Set-ClaudeModuleConfig($Current, [string]$ApiKey, [object[]]$Models) {
    $settings = $Current.Settings
    $ids = [string[]]@($Models | ForEach-Object { $_.id })
    # Keep the model the user picked in /model on a previous start.
    $main = Select-ModuleModel $ids @($settings.model, $settings.env.ANTHROPIC_MODEL, 'claude-sonnet-5') $ids[0]
    $sonnet = Select-ModuleModel $ids @('claude-sonnet-5') $main
    $opus = Select-ModuleModel $ids @('claude-opus-5-5', 'claude-opus-5') $sonnet
    $values = [ordered]@{
        ANTHROPIC_BASE_URL = $ModuleBaseUrl
        ANTHROPIC_AUTH_TOKEN = $ApiKey
        ANTHROPIC_API_KEY = ''
        ANTHROPIC_DEFAULT_SONNET_MODEL = $sonnet
        ANTHROPIC_DEFAULT_OPUS_MODEL = $opus
        ANTHROPIC_DEFAULT_HAIKU_MODEL = (Select-ModuleModel $ids @('claude-haiku-4-5-20251001') $sonnet)
        ANTHROPIC_DEFAULT_FABLE_MODEL = (Select-ModuleModel $ids @('claude-fable-5-1', 'claude-fable-5') $opus)
        CLAUDE_CODE_USE_BEDROCK = '0'
        CLAUDE_CODE_USE_VERTEX = '0'
        CLAUDE_CODE_USE_FOUNDRY = '0'
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'
        # ModuleAPI caps Claude models at 260K tokens; without this Claude Code assumes 1M and compacts too late.
        CLAUDE_CODE_DISABLE_1M_CONTEXT = '1'
        # Window for GPT, Gemini and other non-Claude IDs; without it Claude Code warns about an unknown model on start.
        CLAUDE_CODE_MAX_CONTEXT_TOKENS = '200000'
    }
    foreach ($name in $values.Keys) { $settings.env | Add-Member -MemberType NoteProperty -Name $name -Value $values[$name] -Force }
    # Earlier versions of this setup pinned these; they would override the model chosen in /model.
    $settings.env.PSObject.Properties.Remove('ANTHROPIC_MODEL')
    $settings.env.PSObject.Properties.Remove('CLAUDE_CODE_SUBAGENT_MODEL')
    $settings | Add-Member -MemberType NoteProperty -Name model -Value $main -Force
    $providers = @{ anthropic = 'Anthropic'; openai = 'OpenAI'; deepseek = 'DeepSeek'; google = 'Google'; 'z.ai' = 'Z.AI'; xai = 'xAI' }
    $options = @($Models | ForEach-Object {
        $provider = if ($providers.ContainsKey([string]$_.owned_by)) { $providers[[string]$_.owned_by] } else { [string]$_.owned_by }
        [PSCustomObject]@{ model = [string]$_.id; description = ($provider + ' через ModuleAPI').Trim() }
    })
    $settings | Add-Member -MemberType NoteProperty -Name modelPicker -Value ([PSCustomObject]@{ replaceBuiltInOptions = $true; options = $options }) -Force
    # A former gateway's credential helper must not override the newly configured token.
    $settings.PSObject.Properties.Remove('apiKeyHelper')
    $json = ConvertTo-Json -InputObject $settings -Depth 100
    $file = $Current.File
    if ($Current.Exists -and $json -ceq $Current.Json) { return @{ File = $file; Backup = $null; Changed = $false; Model = $main } }

    $root = Split-Path -Parent $file
    [IO.Directory]::CreateDirectory($root) | Out-Null
    $stamp = [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
    $backup = Join-Path $root ('settings.before-moduleapi-' + $stamp + '.json')
    if ($Current.Exists) {
        if ([IO.File]::ReadAllText($file, [Text.Encoding]::UTF8) -cne $Current.Original) { throw 'settings.json изменился во время настройки. Закройте Claude Code и повторите запуск.' }
        [IO.File]::Copy($file, $backup, $false)
    } else { [IO.File]::WriteAllText($backup, '{}', (New-Object Text.UTF8Encoding($false))) }
    $temporary = Join-Path $root ('settings.moduleapi-' + $stamp + '.tmp')
    [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
    if ($Current.Exists) { [IO.File]::Replace($temporary, $file, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $file) }
    $check = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($file, [Text.Encoding]::UTF8))
    if ($check.env.ANTHROPIC_AUTH_TOKEN -cne $ApiKey -or $check.env.ANTHROPIC_BASE_URL -ne $ModuleBaseUrl -or $check.model -ne $main -or @($check.modelPicker.options).Count -ne $ids.Count) {
        [IO.File]::Copy($backup, $file, $true)
        throw 'Проверка сохранённых настроек не прошла. Восстановлена резервная копия.'
    }
    return @{ File = $file; Backup = $backup; Changed = $true; Model = $main }
}

function Find-ClaudeCode {
    $command = Get-Command claude -CommandType Application -All -ErrorAction Ignore |
        Where-Object { @('.exe', '.cmd', '.bat') -contains [IO.Path]::GetExtension($_.Source).ToLowerInvariant() } |
        Select-Object -First 1
    if ($command) { return $command.Source }
    $native = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\bin\claude.exe'
    if (Test-Path -LiteralPath $native -PathType Leaf) { return $native }
    return $null
}

function Get-ClaudeCodeVersion([string]$Executable) {
    $output = & $Executable --version | Select-Object -First 1
    if ([string]$output -match '(\d+\.\d+\.\d+)') { return [version]$matches[1] }
    return $null
}

function Install-ClaudeCode {
    Write-Host 'Claude Code не найден. Устанавливаю официальным установщиком Anthropic (claude.ai/install.ps1, без прав администратора)...'
    & powershell.exe -NoLogo -NoProfile -Command '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://claude.ai/install.ps1 | iex'
    if ($LASTEXITCODE -ne 0) { throw "Установка Claude Code не удалась (код $LASTEXITCODE). Установите его по https://code.claude.com/docs/en/setup и запустите этот файл снова." }
    $installed = Find-ClaudeCode
    if (-not $installed) { throw 'Claude Code установлен, но не найден. Откройте файл ещё раз.' }
    return $installed
}

if ($FunctionsOnly) { return }
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$apiKey = $null
try {
    Write-Host ''
    Write-Host 'ModuleAPI — Claude Code для Windows' -ForegroundColor Cyan
    Write-Host 'Подключаю Claude Code ко всем моделям вашего ключа и запускаю его. Права администратора не нужны.'
    $current = Read-ClaudeSettings (Get-ClaudeConfigRoot)
    $apiKey = Get-SavedModuleKey $current.Settings ([Environment]::GetEnvironmentVariable('MODULE_API_KEY', 'User'))
    $models = $null
    if ($apiKey) {
        Write-Host 'Найден сохранённый ключ ModuleAPI, проверяю...'
        $models = Get-ModuleModels $apiKey
        if (-not $models) { Write-Host 'Сохранённый ключ больше не принимается. Вставьте новый.' -ForegroundColor Yellow }
    }
    while (-not $models) {
        $secret = Read-Host 'Вставьте ключ ModuleAPI и нажмите Enter (ввод скрыт)' -AsSecureString
        $apiKey = (New-Object Management.Automation.PSCredential('ModuleAPI', $secret)).GetNetworkCredential().Password.Trim().Trim('"', "'")
        if (-not $apiKey) { throw 'Ключ не введён. Настройки не изменены.' }
        if ($apiKey -notmatch '^sk-[A-Za-z0-9_-]{10,}$') { Write-Host 'Нужен полный ключ, начинающийся с sk-, без кавычек и Bearer.' -ForegroundColor Yellow; continue }
        Write-Host 'Проверяю ключ (без платной генерации)...'
        $models = Get-ModuleModels $apiKey
        if (-not $models) { Write-Host 'Ключ не принят: неверный или отключён. Проверьте его в личном кабинете → «Ключи API».' -ForegroundColor Yellow }
    }
    $result = Set-ClaudeModuleConfig $current $apiKey $models
    Write-Host ('Ключ принят. Моделей в Claude Code: ' + $models.Count + '. Модель при запуске: ' + $result.Model) -ForegroundColor Green
    if ($result.Changed) {
        Write-Host ('Настройки: ' + $result.File)
        Write-Host ('Резервная копия прежних настроек: ' + $result.Backup)
    }

    $claude = Find-ClaudeCode
    if (-not $claude) { $claude = Install-ClaudeCode }
    $version = Get-ClaudeCodeVersion $claude
    if ($version -and $version -lt $PickerMinimumVersion) {
        Write-Host "Claude Code $version устарел: список всех моделей в /model появился в версии $PickerMinimumVersion. Обновляю..."
        & $claude update
        $version = Get-ClaudeCodeVersion $claude
    }
    if (-not $version -or $version -lt $PickerMinimumVersion) {
        Write-Host "Не удалось обновить Claude Code до $PickerMinimumVersion. Пока /model не покажет список, выбирайте модель командой /model <имя>, например /model gpt-5.6-luna." -ForegroundColor Yellow
    }
    Write-Host ''
    Write-Host 'Сменить модель: команда /model внутри Claude Code. Проверить подключение: /status.'
    Write-Host 'В следующий раз просто запустите этот файл снова: ключ спрашиваться не будет.'
    Write-Host ('Запускаю Claude Code в папке ' + (Get-Location).Path + ' ...') -ForegroundColor Cyan
    Write-Host ''
    & $claude
} catch {
    $message = $_.Exception.Message
    if ($apiKey) { $message = $message.Replace($apiKey, '[СКРЫТО]') }
    Write-Host ('ОШИБКА: ' + $message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace
    Write-Host 'Инструкция: https://moduleapi.pro/docs#claudecode'
    exit 1
}
