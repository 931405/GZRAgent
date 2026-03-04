import subprocess

result = subprocess.run(["docker", "compose", "logs", "--tail=50", "backend"], capture_output=True, text=True, cwd=r"d:\OneDrive\Desktop\研究生\国自然\Agent")
print("STDOUT:")
print(result.stdout)
print("STDERR:")
print(result.stderr)
