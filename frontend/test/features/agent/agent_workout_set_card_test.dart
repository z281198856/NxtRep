import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/core/settings/app_preferences.dart';
import 'package:nxtrep/features/profile/domain/profile_models.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

void main() {
  for (final voidSet in [false, true]) {
    testWidgets(
      'workout card previews ${voidSet ? 'void' : 'correction'} before approval',
      (tester) async {
        final api = ApiClient(
          config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
          accessTokenProvider: () => null,
          httpClient: MockClient(
            (_) async => throw StateError('unexpected write'),
          ),
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
            'confirmation_id': 'set-change',
            'operation_type': voidSet
                ? 'workout_set_void'
                : 'workout_set_update',
            'status': 'pending',
            'version': 1,
            'impact': '保留修订历史',
            'after': {
              'preview': {
                'date': '2026-10-05',
                'exercise_name': '哑铃卧推',
                'set_index': 2,
                'before_set': {'weight_kg': '50', 'reps': 10},
                'after_set': voidSet ? null : {'weight_kg': '40', 'reps': 8},
                'volume_before': '1000',
                'volume_after': voidSet ? '500' : '820',
              },
            },
          }),
        ];
        final settings = ValueNotifier<AppSettings?>(null);
        addTearDown(settings.dispose);
        await tester.pumpWidget(
          ValueListenableBuilder<AppSettings?>(
            valueListenable: settings,
            builder: (_, value, _) => AppPreferencesScope(
              settings: value,
              child: MaterialApp(home: AgentPage(controller: controller)),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text(voidSet ? '作废误记训练组' : '更正训练组记录'), findsOneWidget);
        expect(find.text(voidSet ? '确认作废' : '确认更正'), findsOneWidget);
        expect(find.text('2026-10-05 · 哑铃卧推 · 第 2 组'), findsOneWidget);
        expect(find.text('原记录：50 公斤 × 10 次'), findsOneWidget);
        expect(find.text('保留修订历史，已有训练计划不变'), findsOneWidget);
        expect(
          find.text('本次记录训练量：1000 → ${voidSet ? '500' : '820'} 公斤·次'),
          findsOneWidget,
        );
        expect(
          find.text('更正为：40 公斤 × 8 次'),
          voidSet ? findsNothing : findsOneWidget,
        );
        expect(
          find.text('确认后此组不再计入有效训练，其他组保留'),
          voidSet ? findsOneWidget : findsNothing,
        );
        expect(find.text('调整份量'), findsNothing);
        expect(tester.takeException(), isNull);
        settings.value = const AppSettings(
          unitSystem: 'imperial',
          timezone: 'Asia/Shanghai',
          privacyMode: 'private',
          shareAnonymousAnalytics: false,
          version: 1,
        );
        await tester.pumpAndSettle();
        expect(find.text('原记录：110.2 lb × 10 次'), findsOneWidget);
        expect(
          find.text('更正为：88.2 lb × 8 次'),
          voidSet ? findsNothing : findsOneWidget,
        );
        expect(
          controller
              .confirmations
              .single
              .after?['preview']['before_set']['weight_kg'],
          '50',
        );
      },
    );
  }
}
