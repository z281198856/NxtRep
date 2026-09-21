import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/features/onboarding/domain/onboarding_models.dart';

void main() {
  test(
    'first-run training modes map to backend-compatible equipment codes',
    () {
      expect(TrainingMode.values, [
        TrainingMode.bodyweight,
        TrainingMode.gymEquipment,
      ]);
      expect(TrainingMode.bodyweight.equipmentCodes, ['bodyweight']);
      expect(TrainingMode.gymEquipment.equipmentCodes, [
        'barbell',
        'dumbbell',
        'cable',
        'rack',
      ]);
    },
  );
}
