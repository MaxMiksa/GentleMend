# Project Notes

## Skill File Paths
- Symptom: 读取本地 skill 的 `SKILL.md` 时，按习惯去 `~/.codex/...` 或 `~/.cc-switch/...` 猜路径，结果连续出现找不到文件。
- Cause: 这个环境里的 skills 分散在不同根目录，不能靠目录习惯推断；应以会话里列出的完整 path 为准。
- Fix: 读取 skill 时直接使用技能清单里给出的完整 `file:` 路径，不要手工改写成别的技能根目录。
