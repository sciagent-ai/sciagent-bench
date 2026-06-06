#!/bin/bash
# Stream-mode isolated test. Each agent turn / tool_call / tool_result
# prints as it happens, so we can see live whether claude is doing real
# work or genuinely stuck.
#
# Usage (from sciagent-bench/):
#   ./cc_isolate_stream.sh
#
# Kills any prior claude -p in flight first.
set -u

pkill -f "claude -p" 2>/dev/null
sleep 1

# Make sure prompt + isolated workdir exist.
python3 -c "import yaml; open('/tmp/photonics_prompt.txt','w').write(yaml.safe_load(open('tasks/photonics.yaml'))['prompt'])"
rm -rf /tmp/cc-iso
mkdir -p /tmp/cc-iso
cp /Users/shrutibadhwar/Documents/2026/testpackage/sciagent-tasks/nowtasks/photonics.pdf /tmp/cc-iso/

cd /tmp/cc-iso
echo "cwd: $(pwd)"
echo "starting claude in stream-json mode — events will appear live"
echo "press Ctrl-C to abort"
echo "---"

env -u ANTHROPIC_API_KEY claude -p \
  --output-format stream-json \
  --verbose \
  --include-partial-messages \
  --model sonnet \
  "$(cat /tmp/photonics_prompt.txt)" \
  </dev/null
