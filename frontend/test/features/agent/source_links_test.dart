import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/features/agent/presentation/source_links.dart';

void main() {
  test(
    'source parsing retains titles, deduplicates and rejects credentials',
    () {
      final links = SourceLink.fromText(
        '[研究](https://example.org/paper) https://example.org/paper '
        '[危险](javascript:alert) https://user:secret@example.org/private',
      );
      expect(links.length, 1);
      expect(links.single.title, '研究');
      expect(links.single.uri.toString(), 'https://example.org/paper');
    },
  );
  testWidgets('source card opens exact URL and reports browser failure', (
    tester,
  ) async {
    Uri? opened;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SourceLinks(
            content: '[研究](https://example.org/paper)',
            openUrl: (uri) async {
              opened = uri;
              return false;
            },
          ),
        ),
      ),
    );
    await tester.tap(find.text('来源：example.org'));
    await tester.pumpAndSettle();
    expect(opened.toString(), 'https://example.org/paper');
    expect(find.text('暂时无法打开来源。'), findsOneWidget);
    expect(find.text('复制链接'), findsOneWidget);
  });

  test('legacy search metadata and long URLs stay out of reply prose', () {
    const content =
        '训练后先休息，照片估算仍有误差。\n\n查询来源（搜索摘要）：\n'
        '- 研究 / 查询时间 2026-10-05T10:51:59.101391+00:00\n'
        '  https://example.org/article/opaque-id-123?tracking=long\n'
        '- 其他来源\nhttps://other.org/page';
    expect(SourceLink.replyText(content), '训练后先休息，照片估算仍有误差。');
    expect(SourceLink.fromText(content).first.uri.host, 'example.org');
    expect(
      SourceLink.replyText('建议观察恢复。\n\n[来源](https://example.org/page)'),
      '建议观察恢复。',
    );
    expect(
      SourceLink.replyText('查询时间：2026-10-05T10:51:59+00:00\n不确定性仍需说明。'),
      '不确定性仍需说明。',
    );
    expect(
      SourceLink.replyText(
        '恢复建议。\n\n来源示例：文章标题（搜索摘要）[详细](https://example.org/paper)',
      ),
      '恢复建议。',
    );
  });

  testWidgets('many retrieved URLs render a single compact source link', (
    tester,
  ) async {
    Uri? opened;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SourceLinks(
            content: 'https://example.org/long-id https://other.org/page',
            openUrl: (uri) async {
              opened = uri;
              return true;
            },
          ),
        ),
      ),
    );
    expect(find.byType(Card), findsNothing);
    expect(find.text('来源：example.org'), findsOneWidget);
    expect(find.textContaining('other.org'), findsNothing);
    await tester.tap(find.text('来源：example.org'));
    expect(opened.toString(), 'https://example.org/long-id');
  });
}
