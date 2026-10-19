#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if ! codex login status; then
  echo "Codex OAuth 未登录。请先运行: codex login" >&2
  exit 1
fi

exec .venv/bin/liveclip agent-clipping-eval \
  --transcript /Users/junhuaxu/autoclip/tests/fixtures/8-30-full-transcript.srt \
  --output /Users/junhuaxu/autoclip/data/evaluations/agent-v2-oauth-full-v4-20260928/agent-run-result.json \
  --state-dir /Users/junhuaxu/autoclip/data/evaluations/agent-v2-oauth-full-v4-20260928/state \
  --run-id agent_v2_oauth_full_v4_20260928 \
  --task '完整冷启动验收：严格按Skill进行一次全字幕的时间顺序重叠覆盖扫描，不得只抽查或依赖搜索。分别发现short_highlight与mini_lesson；同主题短版和长版可并存，跨Profile不得互删。先高召回保存草稿，再按Profile做完整Global Review。复核每一个mini_lesson时，必须重新查看它的完整上下文，找出其中每一个独立完整且满足45到90秒的短单元；复核相邻短片时也要寻找从必要前提到最终结论的最短完整长版。最终边界须独立可懂：逐字检查开头对片外步骤、分类和前文的指代；检查紧邻前文中命名主题或比较对象的定位句；对每条长片至少测试一个更窄的内部边界。结尾覆盖同一话题或同一参与者的最终闭环，不得用寒暄、CTA、设备调试或无关内容补时。现场诊断必须包含足以理解问题的原始提问或演唱，并覆盖纠正、重试、比较和自然结束。每条最终候选独立评分，无通过阈值且不做内容风险审查；低分但有用的候选仍保留。所有候选修复和补召回完成后，调用save_global_review逐条登记并冻结；随后用批量标题工具为每条final候选生成面向小白、准确、有吸引力的多个标题。依靠finish做整组技术校验，不要逐条重复调用validator。没有音频证据就不得声称字幕已校准。不得依赖、猜测或硬编码Benchmark时间和数量。' \
  --reasoning-effort high \
  --max-turns 180
