import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/theme/app_theme.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_management_page.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';
import 'package:nxtrep/features/agent/presentation/conversation_history.dart';

class _HistoryApi {
  _HistoryApi() {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day, 12);
    rows = [
      _row('today', '午饭份量调整', today),
      _row(
        'yesterday',
        '史密斯上斜推胸记录',
        DateTime(today.year, today.month, today.day - 1, 16),
      ),
      _row(
        'older',
        '睡眠与恢复安排',
        DateTime(today.year, today.month, today.day - 3, 18),
      ),
    ];
    api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient(_handle),
    );
    controller = AgentController(AgentRepository(api));
  }

  Map<String, dynamic> _row(String id, String title, DateTime at) => {
    'id': id,
    'title': title,
    'title_source': 'generated',
    'version': 1,
    'status': 'active',
    'created_at': at.toUtc().toIso8601String(),
    'last_message_at': at.toUtc().toIso8601String(),
    'summary': '内部状态：用户目标和未完成任务，不应该显示在历史列表',
  };
  late final List<Map<String, dynamic>> rows;
  late final ApiClient api;
  late final AgentController controller;
  final requests = <http.Request>[];
  bool failArchive = false;
  bool conflictOnce = false;

  http.Response _response(Object body, [int status = 200]) => http.Response(
    jsonEncode(body),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );

  Future<http.Response> _handle(http.Request request) async {
    requests.add(request);
    if (request.url.path.endsWith('/conversations')) {
      return _response({
        'list': rows
            .where(
              (row) => row['status'] == request.url.queryParameters['status'],
            )
            .toList(),
        'has_more': false,
        'total': rows.length,
      });
    }
    final item = rows.firstWhere(
      (row) => row['id'] == request.url.path.split('/').last,
    );
    if (request.method == 'GET') return _response(item);
    if (request.method == 'PATCH') {
      if (failArchive) {
        return _response({
          'error': {'code': 'ARCHIVE_FAILED', 'message': '归档暂时失败，请重试'},
        }, 500);
      }
      if (conflictOnce) {
        conflictOnce = false;
        item['version'] = 3;
        return _response({
          'error': {
            'code': 'AGENT_CONVERSATION_CONFLICT',
            'message': 'Conversation was modified',
          },
        }, 409);
      }
      final body = jsonDecode(request.body) as Map;
      expect(body['expected_version'], item['version']);
      item['status'] = body['status'] ?? item['status'];
      item['title'] = body['title'] ?? item['title'];
      item['version'] = (item['version'] as int) + 1;
      return _response(item);
    }
    throw StateError('Unexpected request');
  }

  Future<void> mount(WidgetTester tester, {bool chat = false}) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(() {
      controller.dispose();
      api.close();
    });
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: chat
            ? AgentPage(controller: controller)
            : AgentManagementPage(controller: controller),
      ),
    );
    await tester.pumpAndSettle();
  }
}

void main() {
  test('day grouping uses local calendar days across year boundaries and creation fallback', () {
    final now = DateTime(2026, 1, 1, 8);
    final items = [
      AgentConversation(
        id: 'older',
        version: 1,
        lastMessageAt: DateTime(2025, 12, 30, 12),
      ),
      AgentConversation(
        id: 'yesterday',
        version: 1,
        lastMessageAt: DateTime(2025, 12, 31, 23),
      ),
      AgentConversation(
        id: 'today',
        version: 1,
        createdAt: DateTime(2026, 1, 1, 2),
      ),
    ];
    final groups = groupConversationsByDay(items, now: now);
    expect(groups.map((group) => group.label), ['今天', '昨天', '2025年12月30日']);
    expect(groups.first.items.single.id, 'today');
    expect(
      groupConversationsByDay([
        const AgentConversation(id: 'old', version: 1),
      ], now: now).single.label,
      '更早的对话',
    );
  });

  test(
    'UTC timestamps are grouped by their local dates, not UTC date strings',
    () {
      final local = DateTime(2026, 10, 19, 0, 15);
      final json = {
        'id': 'boundary',
        'version': 1,
        'last_message_at': local.toUtc().toIso8601String(),
      };
      final item = AgentConversation.fromJson(json);
      expect(
        groupConversationsByDay([
          item,
        ], now: DateTime(2026, 10, 19, 20)).single.label,
        '今天',
      );
      expect(conversationTimeLabel(item), '00:15');
    },
  );

  testWidgets(
    'history shows date headings and readable titles without Agent state summaries',
    (tester) async {
      final state = _HistoryApi();
      await state.mount(tester);
      expect(find.text('今天'), findsOneWidget);
      expect(find.text('昨天'), findsOneWidget);
      final day = DateTime.parse(state.rows.last['last_message_at'] as String)
          .toLocal();
      expect(find.text('${day.year}年${day.month}月${day.day}日'), findsOneWidget);
      expect(find.textContaining('内部状态'), findsNothing);
      expect(find.text('训练咨询'), findsNothing);
      expect(
        tester.getTopLeft(find.text('午饭份量调整')).dy,
        lessThan(tester.getTopLeft(find.text('史密斯上斜推胸记录')).dy),
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('archive can be found in archived list and restored', (
    tester,
  ) async {
    final state = _HistoryApi();
    await state.mount(tester);
    await tester.tap(find.byTooltip('对话操作').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('归档'));
    await tester.pumpAndSettle();
    expect(find.text('午饭份量调整'), findsNothing);
    expect(find.text('已归档，可以在“已归档”中找回。'), findsOneWidget);
    await tester.tap(find.text('已归档'));
    await tester.pumpAndSettle();
    expect(find.text('午饭份量调整'), findsOneWidget);
    await tester.tap(find.byTooltip('对话操作').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('恢复对话'));
    await tester.pumpAndSettle();
    expect(find.text('午饭份量调整'), findsNothing);
    await tester.tap(find.text('对话'));
    await tester.pumpAndSettle();
    expect(find.text('午饭份量调整'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'archive failure stays visible and retains the conversation row',
    (tester) async {
      final state = _HistoryApi()..failArchive = true;
      await state.mount(tester);
      await tester.tap(find.byTooltip('对话操作').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('归档'));
      await tester.pumpAndSettle();
      expect(find.text('归档暂时失败，请重试'), findsOneWidget);
      expect(find.text('午饭份量调整'), findsOneWidget);
      expect(find.text('刷新列表'), findsOneWidget);
      expect(find.text('已归档，可以在“已归档”中找回。'), findsNothing);
    },
  );

  testWidgets(
    'stale title version is read once before retrying only archive status',
    (tester) async {
      final state = _HistoryApi()..conflictOnce = true;
      await state.mount(tester);
      final old = AgentConversation.fromJson({...state.rows.first});
      expect(await state.controller.archiveConversation(old), isTrue);
      final changes = state.requests
          .where((request) => request.method == 'PATCH')
          .toList();
      expect(changes.length, 2);
      expect(jsonDecode(changes.last.body), {
        'status': 'archived',
        'expected_version': 3,
      });
      expect(
        state.requests
            .where(
              (request) =>
                  request.method == 'GET' &&
                  request.url.path.endsWith('/today'),
            )
            .length,
        1,
      );
    },
  );

  testWidgets('chat entry buttons include text and work at narrow widths', (
    tester,
  ) async {
    final state = _HistoryApi();
    await state.mount(tester, chat: true);
    tester.view.physicalSize = const Size(320, 844);
    await tester.pumpAndSettle();
    expect(
      find.widgetWithText(OutlinedButton, '新建对话').hitTestable(),
      findsOneWidget,
    );
    expect(
      find.widgetWithText(OutlinedButton, '历史对话').hitTestable(),
      findsOneWidget,
    );
    await tester.tap(find.widgetWithText(OutlinedButton, '历史对话'));
    await tester.pumpAndSettle();
    expect(find.text('对话与记忆'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
