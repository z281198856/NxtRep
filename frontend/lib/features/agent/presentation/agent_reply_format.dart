class AgentReplyParts {
  const AgentReplyParts({required this.answer, required this.analysis});

  final String answer;
  final String analysis;
}

AgentReplyParts parseAgentReply(String content) {
  final answerLines = <String>[];
  final analysisLines = <String>[];
  var current = answerLines;
  final labeledLine = RegExp(
    r'^\s*(?:#{1,4}\s*)?(?:\*\*)?(回答|分析)\s*[：:](?:\*\*)?\s*(.*)$',
  );
  final headingLine = RegExp(r'^\s*#{1,4}\s*(回答|分析)\s*$');

  for (final line in content.replaceAll('\r\n', '\n').split('\n')) {
    final match = labeledLine.firstMatch(line) ?? headingLine.firstMatch(line);
    if (match != null) {
      current = match.group(1) == '分析' ? analysisLines : answerLines;
      final inlineText = match.groupCount >= 2 ? match.group(2) : null;
      if (inlineText != null && inlineText.isNotEmpty) {
        current.add(inlineText);
      }
      continue;
    }
    current.add(line);
  }

  return AgentReplyParts(
    answer: _plainLanguage(answerLines.join('\n').trim()),
    analysis: _plainLanguage(analysisLines.join('\n').trim()),
  );
}

String _plainLanguage(String text) {
  return text
      .replaceAllMapped(
        RegExp(r'@?RIR\s*[:=]?\s*(\d+)', caseSensitive: false),
        (match) => '做完还可再做约 ${match.group(1)} 次',
      )
      .replaceAll(RegExp(r'@?RIR', caseSensitive: false), '做完还能再做的次数');
}
