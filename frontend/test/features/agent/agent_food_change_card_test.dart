import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

void main() {
  for (final operation in ['food_update', 'food_delete']) {
    testWidgets(
      '$operation shows reviewable content and correct approval button',
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
            content: '请核对后确认。',
            sequence: 1,
            createdAt: DateTime(2026),
          ),
        ];
        controller.confirmations = [
          AgentConfirmationCard.fromJson({
            'confirmation_id': 'edit',
            'operation_type': operation,
            'status': 'pending',
            'version': 1,
            'impact': '历史饮食保留',
            'before': {
              'food': {
                'name': '燕麦饼',
                'basis_amount_g': '100',
                'kcal': '300',
                'protein_g': '10',
                'carbs_g': '40',
                'fat_g': '11',
              },
            },
            'after': {
              'food': {
                'name': '燕麦饼',
                'basis_amount_g': '100',
                'kcal': '320',
                'protein_g': '10',
                'carbs_g': '40',
                'fat_g': '11',
                'source': 'model_estimated',
                'notes': '其余营养保留',
              },
            },
          }),
        ];
        await tester.pumpWidget(
          MaterialApp(home: AgentPage(controller: controller)),
        );
        await tester.pumpAndSettle();
        expect(
          find.text(operation == 'food_update' ? '修改自定义食品' : '删除自定义食品'),
          findsOneWidget,
        );
        expect(
          find.text(operation == 'food_update' ? '确认修改' : '确认删除'),
          findsOneWidget,
        );
        if (operation == 'food_update') {
          expect(find.text('原：燕麦饼，每 100 克 300 千卡'), findsOneWidget);
          expect(find.text('每 100 克：320 千卡'), findsOneWidget);
        } else {
          expect(find.text('确认后仅移除食品库条目，已保存的饮食和营养统计保留'), findsOneWidget);
        }
        expect(find.text('确认添加'), findsNothing);
        expect(find.text('调整份量'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
