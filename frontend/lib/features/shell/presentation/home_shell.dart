import 'package:flutter/material.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/theme/app_theme.dart';
import '../../agent/data/agent_repository.dart';
import '../../agent/data/proactive_repository.dart';
import '../../agent/presentation/agent_controller.dart';
import '../../agent/presentation/agent_page.dart';
import '../../agent/presentation/proactive_controller.dart';
import '../../auth/presentation/session_controller.dart';
import '../../exercises/data/exercise_repository.dart';
import '../../exercises/presentation/exercise_library_page.dart';
import '../../nutrition/data/nutrition_repository.dart';
import '../../nutrition/presentation/nutrition_controller.dart';
import '../../nutrition/presentation/nutrition_page.dart';
import '../../progress/data/body_repository.dart';
import '../../progress/data/body_progress_repository.dart';
import '../../progress/presentation/body_progress_controller.dart';
import '../../progress/presentation/body_progress_page.dart';
import '../../progress/presentation/progress_controller.dart';
import '../../progress/presentation/progress_page.dart';
import '../../profile/data/profile_repository.dart';
import '../../profile/presentation/profile_controller.dart';
import '../../profile/presentation/profile_page.dart';
import '../../training/data/training_repository.dart';
import '../../training/presentation/plan_controller.dart';
import '../../training/presentation/plan_page.dart';
import '../../training/presentation/today_page.dart';
import '../../training/presentation/training_controller.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.controller});

  final SessionController controller;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;
  late final TrainingController _trainingController;
  late final ImageUploadRepository _imageUploadRepository;
  late final AgentController _agentController;
  late final ProactiveController _proactiveController;
  late final NutritionController _nutritionController;
  late final ProgressController _progressController;
  late final BodyProgressController _bodyProgressController;
  late final PlanController _planController;
  late final ProfileController _profileController;
  late final ExerciseRepository _exerciseRepository;

  @override
  void initState() {
    super.initState();
    _trainingController = TrainingController(
      TrainingRepository(widget.controller.authRepository.apiClient),
    );
    _imageUploadRepository = ImageUploadRepository(
      widget.controller.authRepository.apiClient,
    );
    _agentController = AgentController(
      AgentRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadChatImage,
    );
    _proactiveController = ProactiveController(
      ProactiveRepository(widget.controller.authRepository.apiClient),
    );
    _nutritionController = NutritionController(
      NutritionRepository(widget.controller.authRepository.apiClient),
    );
    _progressController = ProgressController(
      BodyRepository(widget.controller.authRepository.apiClient),
    );
    _bodyProgressController = BodyProgressController(
      BodyProgressRepository(widget.controller.authRepository.apiClient),
      _imageUploadRepository.uploadBodyProgressImage,
    );
    _planController = PlanController(
      TrainingRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadTrainingPlanImage,
    );
    _profileController = ProfileController(
      ProfileRepository(widget.controller.authRepository.apiClient),
    );
    _exerciseRepository = ExerciseRepository(
      widget.controller.authRepository.apiClient,
    );
  }

  @override
  void dispose() {
    _trainingController.dispose();
    _agentController.dispose();
    _proactiveController.dispose();
    _imageUploadRepository.close();
    _nutritionController.dispose();
    _progressController.dispose();
    _bodyProgressController.dispose();
    _planController.dispose();
    _profileController.dispose();
    super.dispose();
  }

  void _selectTab(int value) {
    if (value == 0) {
      _trainingController.refresh();
      _proactiveController.refresh();
    }
    if (value == 1) _planController.refresh();
    if (value == 2) _progressController.refresh();
    setState(() => _index = value);
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      TodayPage(
        username: widget.controller.account?.username ?? '',
        controller: _trainingController,
        proactiveController: _proactiveController,
        exerciseRepository: _exerciseRepository,
        onOpenPlan: () => _selectTab(1),
        onOpenProgress: () => _selectTab(2),
        onOpenAgent: () => _selectTab(3),
        onOpenNutrition: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => NutritionPage(controller: _nutritionController),
          ),
        ),
      ),
      PlanPage(
        controller: _planController,
        onOpenExerciseLibrary: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) =>
                ExerciseLibraryPage(repository: _exerciseRepository),
          ),
        ),
        onAskCoach: (prompt) async {
          _selectTab(3);
          await _agentController.send(prompt);
        },
      ),
      ProgressPage(
        controller: _progressController,
        onOpenBodyProgress: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) =>
                BodyProgressPage(controller: _bodyProgressController),
          ),
        ),
      ),
      AgentPage(controller: _agentController),
      ProfilePage(
        controller: _profileController,
        username: widget.controller.account?.username ?? '',
        loggingOut: widget.controller.submitting,
        onLogout: widget.controller.logout,
      ),
    ];

    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: AppColors.line, width: 0.8)),
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: _selectTab,
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.home_outlined),
              selectedIcon: Icon(Icons.home_rounded),
              label: '首页',
            ),
            NavigationDestination(
              icon: Icon(Icons.bolt_outlined),
              selectedIcon: Icon(Icons.bolt_rounded),
              label: '计划',
            ),
            NavigationDestination(
              icon: Icon(Icons.insights_outlined),
              selectedIcon: Icon(Icons.insights_rounded),
              label: '进展',
            ),
            NavigationDestination(
              icon: Icon(Icons.auto_awesome_outlined),
              selectedIcon: Icon(Icons.auto_awesome_rounded),
              label: 'AI教练',
            ),
            NavigationDestination(
              icon: Icon(Icons.person_outline_rounded),
              selectedIcon: Icon(Icons.person_rounded),
              label: '我的',
            ),
          ],
        ),
      ),
    );
  }
}
