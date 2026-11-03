import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

Future<void> showCard(WidgetTester tester, Map<String, Object?> card) async {
  final api = ApiClient(
    config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
    accessTokenProvider: () => null,
    httpClient: MockClient((_) async => throw StateError('unexpected write')),
  );
  final controller = AgentController(AgentRepository(api));
  addTearDown(controller.dispose);
  addTearDown(api.close);
  controller.messages = [
    AgentMessage(
      id: 'reply',
      role: 'assistant',
      content: '请核对草稿。',
      sequence: 1,
      createdAt: DateTime(2026),
    ),
  ];
  controller.confirmations = [
    AgentConfirmationCard.fromJson({
      'confirmation_id': 'exercise-record',
      'status': 'pending',
      'version': 1,
      'impact': '确认后记录实际训练组',
      ...card,
    }),
  ];
  await tester.pumpWidget(MaterialApp(home: AgentPage(controller: controller)));
  await tester.pumpAndSettle();
}

void main() {
  for (final increase in [false, true]) {
    testWidgets('set count correction shows removed or added sets $increase', (
      tester,
    ) async {
      final before = [
        {'set_id': 'first', 'set_index': 1, 'weight_kg': '60', 'reps': 8},
        {'set_id': 'second', 'set_index': 2, 'weight_kg': '60', 'reps': 8},
      ];
      await showCard(tester, {
        'operation_type': 'workout_record_update',
        'after': {
          'preview': {
            'date': '2026-10-17',
            'exercise_name': '卧推',
            'before_sets': before,
            'after_sets': [
              {...before[0], 'weight_kg': '55'},
              if (increase) {...before[1], 'weight_kg': '55'},
              if (increase)
                {
                  'set_id': null,
                  'set_index': 3,
                  'weight_kg': '55',
                  'reps': 8,
                  'added': true,
                },
            ],
          },
        },
      });
      expect(
        find.text('2026-10-17 · 卧推 · 2 组 → ${increase ? 3 : 1} 组'),
        findsOneWidget,
      );
      expect(
        find.text(increase ? '新增第 3 组：55 公斤 × 8 次' : '作废第 2 组：60 公斤 × 8 次'),
        findsOneWidget,
      );
      expect(find.text('确认更正'), findsOneWidget);
      expect(find.textContaining('set_id'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  for (final append in [false, true]) {
    testWidgets(
      'workout create card previews actual parameters and append context $append',
      (tester) async {
        await showCard(tester, {
          'operation_type': 'workout_record_create',
          'after': {
            'request': {
              'exercise_name': '上斜卧推',
              'weight_kg': '25',
              'sets': 2,
              'reps': 10,
              if (append) 'workout_id': 'real-session-id',
            },
            'preview': {
              'date': '2026-10-08',
              'exercise_name': '上斜卧推',
              'weight_kg': '25',
              'sets': 2,
              'reps': 10,
            },
          },
        });
        expect(find.text(append ? '追加训练动作' : '记录训练动作'), findsOneWidget);
        expect(find.text('确认记录'), findsOneWidget);
        expect(find.text('2026-10-08 · 上斜卧推'), findsOneWidget);
        expect(find.text('25 公斤 · 2 组 · 每组 10 次'), findsOneWidget);
        expect(
          find.text('追加到原训练，保留已记录的其他动作'),
          append ? findsOneWidget : findsNothing,
        );
        expect(find.textContaining('训练保持进行中'), findsOneWidget);
        expect(find.textContaining('real-session-id'), findsNothing);
        expect(find.text('调整份量'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final voidRecord in [false, true]) {
    testWidgets(
      'workout batch card previews each selected group and retained exercises $voidRecord',
      (tester) async {
        final before = [
          {'set_id': 'set-1', 'set_index': 1, 'weight_kg': '60', 'reps': 8},
          {'set_id': 'set-2', 'set_index': 2, 'weight_kg': '60', 'reps': 8},
        ];
        await showCard(tester, {
          'operation_type': voidRecord
              ? 'workout_record_void'
              : 'workout_record_update',
          'after': {
            'preview': {
              'date': '2026-10-08',
              'exercise_name': '杠铃卧推',
              'before_sets': before,
              'after_sets': voidRecord
                  ? []
                  : [
                      for (final item in before) {...item, 'weight_kg': '55'},
                    ],
            },
          },
        });
        expect(find.text(voidRecord ? '撤销误记动作' : '更正动作训练记录'), findsOneWidget);
        expect(find.text(voidRecord ? '确认撤销' : '确认更正'), findsOneWidget);
        expect(find.text('2026-10-08 · 杠铃卧推 · 2 组'), findsOneWidget);
        for (final index in [1, 2]) {
          expect(
            find.text(
              voidRecord
                  ? '撤销第 $index 组：60 公斤 × 8 次'
                  : '第 $index 组：60 公斤 × 8 次 → 55 公斤 × 8 次',
            ),
            findsOneWidget,
          );
        }
        expect(find.text('仅修改所列训练组，保留这次训练的其他动作和已有训练计划'), findsOneWidget);
        expect(
          find.textContaining('原记录和修订历史保留'),
          voidRecord ? findsOneWidget : findsNothing,
        );
        expect(find.textContaining('set-1'), findsNothing);
        expect(find.text('调整份量'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
