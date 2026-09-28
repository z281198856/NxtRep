import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/features/agent/presentation/agent_reply_format.dart';

void main() {
  test('splits a concise answer and analysis', () {
    final parts = parseAgentReply('回答：今天练全身 A。\n\n分析：按你每周三练的计划安排。');

    expect(parts.answer, '今天练全身 A。');
    expect(parts.analysis, '按你每周三练的计划安排。');
  });

  test('handles markdown headings and incomplete streamed replies', () {
    final parts = parseAgentReply('## 回答\n先热身。\n### 分析\n今天安排了训练。');
    final partial = parseAgentReply('- ');

    expect(parts.answer, '先热身。');
    expect(parts.analysis, '今天安排了训练。');
    expect(partial.answer, '-');
    expect(partial.analysis, isEmpty);
  });

  test('explains RIR in older AI replies without changing stored content', () {
    final parts = parseAgentReply('回答：深蹲 3 组，@RIR3。\n分析：RIR 2 表示留有余力。');

    expect(parts.answer, contains('做完还可再做约 3 次'));
    expect(parts.analysis, contains('做完还可再做约 2 次'));
    expect(parts.answer, isNot(contains('RIR')));
  });

  test('handles bold section labels and unexplained RIR without a number', () {
    final parts = parseAgentReply('**回答：** 先用轻重量。\n**分析：** RIR 指保留的余力。');

    expect(parts.answer, '先用轻重量。');
    expect(parts.analysis, '做完还能再做的次数 指保留的余力。');
  });
}
