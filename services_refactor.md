New-Item -ItemType Directory -Name services -Force
Set-Location services
$files = @(
  "__init__.py",
  "config.py",
  "clients.py",
  "embeddings.py",
  "storage.py",
  "templates.py",
  "prompts.py",
  "qna.py",
  "doc_retriever.py"
)
foreach ($f in $files) {
  New-Item -ItemType File -Name $f -Force
}
Set-Location ..
