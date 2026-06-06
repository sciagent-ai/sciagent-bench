#!/bin/bash
# Isolated test: run `claude -p` outside the bench harness so we can see
# whether the hang is claude's behavior on this prompt+cwd, or specific
# to how run_matrix.py spawns the subprocess.
#
# Run from /Users/shrutibadhwar/Documents/2026/testpackage/sciagent-bench:
#   ./cc_isolate_test.sh
# Then a moment later:
#   sleep 30 && ls -lh /tmp/test_a.out && head -c 1500 /tmp/test_a.out
set -u

# Re-derive the photonics prompt from the task YAML.
python3 -c "import yaml; open('/tmp/photonics_prompt.txt','w').write(yaml.safe_load(open('tasks/photonics.yaml'))['prompt'])"

# Stage a fresh isolated workdir with the PDF, same as the cell would have.
rm -rf /tmp/cc-iso
mkdir -p /tmp/cc-iso
cp /Users/shrutibadhwar/Documents/2026/testpackage/sciagent-tasks/nowtasks/photonics.pdf /tmp/cc-iso/

cd /tmp/cc-iso
echo "cwd: $(pwd)"
echo "prompt length: $(wc -c < /tmp/photonics_prompt.txt) chars"
echo "ANTHROPIC_API_KEY in env after strip? ${ANTHROPIC_API_KEY:-no}"
echo "starting claude — output -> /tmp/test_a.out"
set -x

env -u ANTHROPIC_API_KEY claude -p --model sonnet \
  "$(cat /tmp/photonics_prompt.txt)" \
  </dev/null > /tmp/test_a.out 2>&1 &

CC_PID=$!
echo "claude PID: $CC_PID"
echo "tail with: tail -f /tmp/test_a.out"
echo "size check: stat -f%z /tmp/test_a.out"
