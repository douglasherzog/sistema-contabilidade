param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,

    [string]$EnvFilePath = ".env",

    [switch]$AlsoSetProcessEnv
)

$ErrorActionPreference = "Stop"

function Set-OrUpdateEnvVar {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType File -Path $Path -Force | Out-Null
    }

    $lines = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($null -eq $lines) {
        $lines = @()
    }

    $pattern = "^" + [Regex]::Escape($Name) + "="
    $updated = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) {
            $lines[$i] = "$Name=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $lines += "$Name=$Value"
    }

    Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
}

$trustedSourcesJson = '[{"label":"CLT","url":"https://www.planalto.gov.br/ccivil_03/decreto-lei/del5452.htm"}]'

$vars = [ordered]@{
    "AI_ASSISTANT_ENABLED" = "true"
    "AI_API_KEY" = $ApiKey
    "AI_API_URL" = "https://api.openai.com/v1/chat/completions"
    "AI_MODEL" = "gpt-4o-mini"
    "AI_TIMEOUT_SECONDS" = "25"
    "AI_KNOWLEDGE_ENABLED" = "true"
    "AI_KNOWLEDGE_REFRESH_HOURS" = "24"
    "AI_KNOWLEDGE_MAX_CHARS" = "12000"
    "AI_KNOWLEDGE_TOP_K" = "3"
    "AI_TRUSTED_SOURCES" = $trustedSourcesJson
    "AI_KNOWLEDGE_STRICT_WHITELIST" = "true"
    "AI_KNOWLEDGE_ALLOWED_DOMAINS" = "gov.br,planalto.gov.br"
    "AI_KNOWLEDGE_MIN_TRUST_SCORE" = "70"
}

foreach ($entry in $vars.GetEnumerator()) {
    Set-OrUpdateEnvVar -Path $EnvFilePath -Name $entry.Key -Value $entry.Value
    if ($AlsoSetProcessEnv) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
}

Write-Host "Arquivo '$EnvFilePath' atualizado com as variáveis da IA."
if ($AlsoSetProcessEnv) {
    Write-Host "Variáveis também definidas no processo atual do PowerShell."
}
Write-Host "Importante: mantenha a chave AI_API_KEY fora de versionamento."
