# Authentic gpt-4o-mini imports (replacing mocks)
import openai
from semantic_kernel.contents import ChatHistory
from semantic_kernel.core_plugins import ConversationSummaryPlugin
from config.unified_config import UnifiedConfig

# -*- coding: utf-8 -*-
"""
Tests unitaires pour le `AnalysisRunner`.

Ce module contient les tests unitaires pour la classe `AnalysisRunner`,
qui orchestre l'analyse argumentative d'un texte.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
# from tests.async_test_case import AsyncTestCase # Suppression de l'import
from argumentation_analysis.orchestration.analysis_runner import AnalysisRunner


class TestAnalysisRunner(unittest.TestCase):
    """Suite de tests pour la classe `AnalysisRunner`."""
    async def _create_authentic_gpt4o_mini_instance(self):
        """Crée une instance authentique de gpt-4o-mini au lieu d'un mock."""
        config = UnifiedConfig()
        return config.get_kernel_with_gpt4o_mini()
        
    async def _make_authentic_llm_call(self, prompt: str) -> str:
        """Fait un appel authentique à gpt-4o-mini."""
        try:
            kernel = await self._create_authentic_gpt4o_mini_instance()
            result = await kernel.invoke("chat", input=prompt)
            return str(result)
        except Exception as e:
            logger.warning(f"Appel LLM authentique échoué: {e}")
            return "Authentic LLM call failed"

    def setUp(self):
        """Initialisation avant chaque test."""
        self.runner = AnalysisRunner()
        self.test_text = "Ceci est un texte de test pour l'analyse."
        self.mock_llm_service = MagicMock()
        self.mock_llm_service.service_id = "test_service_id"
 
    
    @patch('argumentation_analysis.orchestration.analysis_runner._run_analysis_conversation', new_callable=AsyncMock)
    @patch('argumentation_analysis.orchestration.analysis_runner.create_llm_service')
    async def test_run_analysis_with_llm_service(self, mock_create_llm_service, mock_run_analysis_conversation):
        """Teste l'exécution de l'analyse avec un service LLM fourni."""
        mock_run_analysis_conversation.return_value = "Résultat de l'analyse"
        
        result = await self.runner.run_analysis_async(
            text_content=self.test_text,
            llm_service=self.mock_llm_service
        )
        
        self.assertEqual(result, "Résultat de l'analyse")
        mock_create_llm_service.assert_not_called()
        mock_run_analysis_conversation.assert_called_once_with(
            texte_a_analyser=self.test_text,
            llm_service=self.mock_llm_service
        )

    @patch('argumentation_analysis.orchestration.analysis_runner._run_analysis_conversation', new_callable=AsyncMock)
    @patch('argumentation_analysis.orchestration.analysis_runner.create_llm_service')
    async def test_run_analysis_without_llm_service(self, mock_create_llm_service, mock_run_analysis_conversation):
        """Teste l'exécution de l'analyse sans service LLM fourni."""
        mock_create_llm_service.return_value = self.mock_llm_service
        mock_run_analysis_conversation.return_value = "Résultat de l'analyse"
        
        result = await self.runner.run_analysis_async(text_content=self.test_text)
        
        self.assertEqual(result, "Résultat de l'analyse")
        mock_create_llm_service.assert_called_once()
        mock_run_analysis_conversation.assert_called_once_with(
            texte_a_analyser=self.test_text,
            llm_service=self.mock_llm_service
        )

if __name__ == '__main__':
    unittest.main()