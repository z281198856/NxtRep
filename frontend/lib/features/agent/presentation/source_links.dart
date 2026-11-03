import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

class SourceLink {
  const SourceLink(this.title, this.uri);
  final String title;
  final Uri uri;

  static String replyText(String content) {
    // Older messages persisted a verbose technical source appendix.
    var text = content.replaceFirst(
      RegExp(
        r'\n\s*(?:查询来源（搜索摘要）|查询来源\(搜索摘要\)|查询来源|搜索来源|参考来源|参考资料|资料来源)\s*[:：][\s\S]*$',
      ),
      '',
    );
    text = text.replaceAllMapped(
      RegExp(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)'),
      (match) => {'来源', '参考来源', '查看来源'}.contains(match.group(1))
          ? ''
          : match.group(1)!,
    );
    text = text.replaceAll(RegExp(r'https?://[^\s<>）)\]，。；]+'), '');
    if (SourceLink.fromText(content).isNotEmpty) {
      text = text
          .split('\n')
          .where(
            (line) =>
                !RegExp(r'^\s*(?:[-*•]\s*)?(?:来源示例|参考来源|资料来源|搜索来源|来源)\s*[:：]')
                    .hasMatch(line),
          )
          .join('\n');
    }
    text = text
        .split('\n')
        .where(
          (line) => !RegExp(
            r'^\s*(?:[-*•]\s*)?(?:查询时间|搜索时间|searched_at|cache_hit|cache_age_seconds|cache_ttl_seconds|tool_call_id)\s*[:：=]',
          ).hasMatch(line),
        )
        .join('\n');
    text = text.replaceAll(
      RegExp(r'^\s*(?:[-*•]\s*)?(?:来源|参考来源)\s*[:：]?\s*$', multiLine: true),
      '',
    );
    return text.replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
  }

  static List<SourceLink> fromText(String text) {
    final links = <String, SourceLink>{};
    void add(String title, String value) {
      final uri = Uri.tryParse(value);
      if (uri == null ||
          !{'http', 'https'}.contains(uri.scheme) ||
          uri.host.isEmpty ||
          uri.userInfo.isNotEmpty) {
        return;
      }
      links.putIfAbsent(uri.toString(), () => SourceLink(title, uri));
    }

    for (final match in RegExp(
      r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)',
    ).allMatches(text)) {
      add(match.group(1)!, match.group(2)!);
    }
    for (final match in RegExp(r'https?://[^\s<>）)\]，。；]+').allMatches(text)) {
      final value = match.group(0)!;
      add(Uri.tryParse(value)?.host ?? '查看来源', value);
    }
    return links.values.take(5).toList(growable: false);
  }
}

class SourceLinks extends StatelessWidget {
  const SourceLinks({super.key, required this.content, this.openUrl});
  final String content;
  final Future<bool> Function(Uri)? openUrl;

  Future<void> _open(BuildContext context, Uri uri) async {
    var opened = false;
    try {
      opened =
          await (openUrl?.call(uri) ??
              launchUrl(uri, mode: LaunchMode.externalApplication));
    } catch (_) {
      opened = false;
    }
    if (!opened && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('暂时无法打开来源。'),
          action: SnackBarAction(
            label: '复制链接',
            onPressed: () =>
                Clipboard.setData(ClipboardData(text: uri.toString())),
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (final source in SourceLink.fromText(content).take(1))
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: InkWell(
            onTap: () => _open(context, source.uri),
            borderRadius: BorderRadius.circular(6),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.link_rounded, size: 14),
                  const SizedBox(width: 4),
                  Flexible(
                    child: Text(
                      '来源：${source.uri.host}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                  const SizedBox(width: 4),
                  const Icon(Icons.open_in_new_rounded, size: 12),
                ],
              ),
            ),
          ),
        ),
    ],
  );
}
