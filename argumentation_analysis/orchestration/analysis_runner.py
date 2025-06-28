﻿# orchestration/analysis_runner.py
import argumentation_analysis.core.environment  # Auto-activation environnement intelligent
import sys
import os
# Ajout pour résoudre les problèmes d'import de project_core
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_script_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import time
import traceback
import asyncio
import logging
import json
import random
import re
from typing import List, Optional, Union, Any, Dict

from argumentation_analysis.core.jvm_setup import initialize_jvm
from argumentation_analysis.paths import LIBS_DIR # Nécessaire pour initialize_jvm

import jpype # Pour la vérification finale de la JVM
# Imports pour le hook LLM
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents.chat_message_content import ChatMessageContent as SKChatMessageContent # Alias pour éviter conflit
from semantic_kernel.kernel import Kernel as SKernel # Alias pour éviter conflit avec Kernel de SK
 # Imports Semantic Kernel
import semantic_kernel as sk
from semantic_kernel.contents import ChatMessageContent
from semantic_kernel.exceptions.kernel_exceptions import KernelInvokeException
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, AzureChatCompletion # Pour type hint
from semantic_kernel.functions.kernel_arguments import KernelArguments
from semantic_kernel.contents.chat_history import ChatHistory

# Correct imports
from argumentation_analysis.core.shared_state import RhetoricalAnalysisState
from argumentation_analysis.core.state_manager_plugin import StateManagerPlugin
from argumentation_analysis.agents.core.pm.pm_agent import ProjectManagerAgent
from argumentation_analysis.agents.core.informal.informal_agent import InformalAnalysisAgent
from argumentation_analysis.agents.core.logic.propositional_logic_agent import PropositionalLogicAgent
from argumentation_analysis.agents.core.extract.extract_agent import ExtractAgent

async def _run_analysis_conversation(
    texte_a_analyser: str,
    llm_service: Union[OpenAIChatCompletion, AzureChatCompletion] # Service LLM passé en argument
    ):
    run_start_time = time.time()
    run_id = random.randint(1000, 9999)
    print("\n=====================================================")
    print(f"== Début de l'Analyse Collaborative (Run_{run_id}) ==")
    print("=====================================================")
    run_logger = logging.getLogger(f"Orchestration.Run.{run_id}")
    run_logger.info("--- Début Nouveau Run ---")

    run_logger.info(f"Type de llm_service: {type(llm_service)}")

    class RawResponseLogger:
        def __init__(self, logger_instance): self.logger = logger_instance
        def on_chat_completion_response(self, message, raw_response):
            self.logger.debug(f"Raw LLM Response for message ID {message.id if hasattr(message, 'id') else 'N/A'}: {raw_response}")

    if hasattr(llm_service, "add_chat_hook_handler"):
        raw_logger_hook = RawResponseLogger(run_logger)
        llm_service.add_chat_hook_handler(raw_logger_hook)
        run_logger.info("RawResponseLogger hook ajouté au service LLM.")
    else:
        run_logger.warning("Le service LLM ne supporte pas add_chat_hook_handler. Le RawResponseLogger ne sera pas actif.")

    if not llm_service or not hasattr(llm_service, 'service_id'):
         run_logger.critical("❌ Service LLM invalide ou manquant fourni à run_analysis_conversation.")
         raise ValueError("Un service LLM valide est requis.")
    run_logger.info(f"Utilisation du service LLM fourni: ID='{llm_service.service_id}'")

    local_state: Optional[RhetoricalAnalysisState] = None
    local_kernel: Optional[sk.Kernel] = None
    local_group_chat: Optional[Any] = None # AgentGroupChat non disponible
    local_state_manager_plugin: Optional[StateManagerPlugin] = None

    agent_list_local: List[Any] = []

    try:
        run_logger.info("1. Création instance état locale...")
        local_state = RhetoricalAnalysisState(initial_text=texte_a_analyser)
        run_logger.info(f"   Instance état locale créée (id: {id(local_state)}) avec texte (longueur: {len(texte_a_analyser)}).")

        run_logger.info("2. Création instance StateManagerPlugin locale...")
        local_state_manager_plugin = StateManagerPlugin(local_state)
        run_logger.info(f"   Instance StateManagerPlugin locale créée (id: {id(local_state_manager_plugin)}).")

        run_logger.info("3. Création Kernel local...")
        local_kernel = sk.Kernel()
        local_kernel.add_service(llm_service)
        run_logger.info(f"   Service LLM '{llm_service.service_id}' ajouté.")
        local_kernel.add_plugin(local_state_manager_plugin, plugin_name="StateManager")
        run_logger.info(f"   Plugin 'StateManager' (local) ajouté.")

        run_logger.info("4. Création et configuration des instances d'agents refactorés...")
        llm_service_id_str = llm_service.service_id

        pm_agent_refactored = ProjectManagerAgent(kernel=local_kernel, agent_name="ProjectManagerAgent_Refactored")
        pm_agent_refactored.setup_agent_components(llm_service_id=llm_service_id_str)
        run_logger.info(f"   Agent {pm_agent_refactored.name} instancié et configuré.")

        informal_agent_refactored = InformalAnalysisAgent(kernel=local_kernel, agent_name="InformalAnalysisAgent_Refactored")
        informal_agent_refactored.setup_agent_components(llm_service_id=llm_service_id_str)
        run_logger.info(f"   Agent {informal_agent_refactored.name} instancié et configuré.")

        pl_agent_refactored = PropositionalLogicAgent(kernel=local_kernel, agent_name="PropositionalLogicAgent_Refactored")
        pl_agent_refactored.setup_agent_components(llm_service_id=llm_service_id_str)
        run_logger.info(f"   Agent {pl_agent_refactored.name} instancié et configuré.")

        extract_agent_refactored = ExtractAgent(kernel=local_kernel, agent_name="ExtractAgent_Refactored")
        extract_agent_refactored.setup_agent_components(llm_service_id=llm_service_id_str)
        run_logger.info(f"   Agent {extract_agent_refactored.name} instancié et configuré.")

        run_logger.debug(f"   Plugins enregistrés dans local_kernel après setup des agents: {list(local_kernel.plugins.keys())}")

        run_logger.info("5. Création du groupe de chat et lancement de l'orchestration...")

        # Rassembler les agents actifs
        agents = [pm_agent_refactored, informal_agent_refactored, pl_agent_refactored, extract_agent_refactored]
        active_agents = [agent for agent in agents if agent is not None]

        if not active_agents:
            run_logger.critical("Aucun agent actif n'a pu être initialisé. Annulation de l'analyse.")
            return {"status": "error", "message": "Aucun agent actif."}

        run_logger.info(f"Agents actifs pour la conversation: {[agent.name for agent in active_agents]}")

        # Création de l'historique de chat et message initial
        chat = ChatHistory()
        initial_user_message = (
            "Vous êtes une équipe d'analystes experts en argumentation. Votre mission est d'analyser le texte suivant. "
            "Le ProjectManagerAgent doit commencer par définir les tâches. Les autres agents attendent ses instructions. "
            f"Le texte à analyser est:\n\n---\n{texte_a_analyser}\n---"
        )
        chat.add_user_message(initial_user_message)
        run_logger.info("Historique de chat initialisé avec le message utilisateur.")

        run_logger.info("Début de la boucle de conversation manuelle...")

        full_history = chat
        max_turns = 15

        current_agent = None
        for i in range(max_turns):
            run_logger.info(f"--- Tour de conversation {i+1}/{max_turns} ---")

            if i == 0:
                next_agent = pm_agent_refactored
            else:
                if current_agent.name != pm_agent_refactored.name:
                    next_agent = pm_agent_refactored
                    run_logger.info("Le tour précédent a été exécuté par un agent travailleur. Le contrôle revient au ProjectManagerAgent.")
                else:
                    last_message_content = full_history.messages[-1].content
                    next_agent_name_str = "TERMINATE"
                    match = re.search(r'designate_next_agent\(agent_name="([^"]+)"\)', last_message_content)
                    if match:
                        next_agent_name_str = match.group(1)
                        run_logger.info(f"Prochain agent désigné par le PM : '{next_agent_name_str}'")
                        next_agent = next((agent for agent in active_agents if agent.name == next_agent_name_str), None)
                    else:
                        run_logger.warning(f"Le PM n'a pas désigné de prochain agent. Réponse: {last_message_content[:150]}... Fin de la conversation.")
                        next_agent = None

            if not next_agent:
                run_logger.info(f"Aucun prochain agent valide trouvé. Fin de la boucle de conversation.")
                break

            current_agent = next_agent

            run_logger.info(f"Agent sélectionné pour ce tour: {next_agent.name}")

            arguments = KernelArguments(chat_history=full_history)
            result_stream = next_agent.invoke_stream(local_kernel, arguments=arguments)

            response_messages = [message async for message in result_stream]

            if not response_messages:
                run_logger.warning(f"L'agent {next_agent.name} n'a retourné aucune réponse. Fin de la conversation.")
                break

            last_message_content = ""
            for message_list in response_messages:
                for msg_content in message_list:
                    full_history.add_message(message=msg_content)
                    last_message_content = msg_content.content

            run_logger.info(f"Réponse de {next_agent.name} reçue et ajoutée à l'historique.")

            if current_agent.name == pm_agent_refactored.name and last_message_content:
                run_logger.info("Détection des appels d'outils planifiés par le ProjectManagerAgent...")
                task_match = re.search(r'StateManager\.add_analysis_task\(description="([^"]+)"\)', last_message_content)
                if task_match:
                    task_description = task_match.group(1)
                    run_logger.info(f"Appel à 'add_analysis_task' trouvé. Description: '{task_description}'")
                    try:
                        result = await local_kernel.invoke(
                            plugin_name="StateManager",
                            function_name="add_analysis_task",
                            arguments=KernelArguments(description=task_description)
                        )
                        active_task_id = result.value
                        run_logger.info(f"Exécution de 'add_analysis_task' réussie. Tâche '{active_task_id}' créée.")
                    except Exception as e:
                        run_logger.error(f"Erreur lors de l'exécution de 'add_analysis_task': {e}", exc_info=True)

            elif current_agent.name != pm_agent_refactored.name and last_message_content:
                run_logger.info(f"Traitement de la réponse de l'agent travailleur: {current_agent.name}")
                try:
                    last_task_id = local_state.get_last_task_id()
                    if last_task_id:
                        run_logger.info(f"La tâche active est '{last_task_id}'. Mise à jour de l'état avec la réponse.")
                        try:
                            response_data = json.loads(last_message_content)
                            if "identified_arguments" in response_data:
                                await local_kernel.invoke(
                                    plugin_name="StateManager",
                                    function_name="add_identified_arguments",
                                    arguments=KernelArguments(arguments=response_data["identified_arguments"])
                                )
                                run_logger.info(f"Arguments identifiés par {current_agent.name} ajoutés à l'état.")
                            elif "identified_fallacies" in response_data:
                                await local_kernel.invoke(
                                    plugin_name="StateManager",
                                    function_name="add_identified_fallacies",
                                    arguments=KernelArguments(fallacies=response_data["identified_fallacies"])
                                )
                                run_logger.info(f"Sophismes identifiés par {current_agent.name} ajoutés à l'état.")
                        except json.JSONDecodeError:
                            run_logger.warning(f"La réponse de {current_agent.name} n'est pas un JSON valide. Contenu: {last_message_content}")

                        await local_kernel.invoke(
                            plugin_name="StateManager",
                            function_name="mark_task_as_answered",
                            arguments=KernelArguments(task_id=last_task_id, answer=last_message_content)
                        )
                        run_logger.info(f"Tâche '{last_task_id}' marquée comme terminée.")
                    else:
                        run_logger.warning("Agent travailleur a répondu mais aucune tâche active trouvée dans l'état.")
                except Exception as e:
                    run_logger.error(f"Erreur lors de la mise à jour de l'état avec la réponse de {current_agent.name}: {e}", exc_info=True)

        run_logger.info("Boucle de conversation manuelle terminée.")

        if full_history:
            run_logger.debug("=== Transcription de la Conversation ===")
            for message in full_history:
                author_info = f"Role: {message.role}"
                run_logger.debug(f"[{author_info}]:\n{message.content}")
            run_logger.debug("======================================")

        final_analysis = {}
        try:
            json_str = local_state.to_json()
            if isinstance(json_str, str):
                final_analysis = json.loads(json_str)
            else:
                run_logger.error(f"local_state.to_json() a retourné un type inattendu: {type(json_str)}. Repr: {repr(local_state)}")
                # Tenter d'obtenir une représentation textuelle sûre
                final_analysis = {"error": "Invalid type from to_json()", "type": str(type(json_str))}

        except Exception as e_json:
            run_logger.error(f"Erreur lors de la sérialisation de l'état final: {e_json}", exc_info=True)
            final_analysis = {"error": "Failed to serialize final state", "details": str(e_json)}

        history_list = []
        if full_history:
            for message in full_history:
                history_list.append({
                    "role": str(message.role),
                    "author_name": getattr(message, 'author_name', None),
                    "content": str(message.content)
                })

        run_logger.info(f"--- Fin Run_{run_id} ---")

        final_output = {"status": "success", "analysis": final_analysis, "history": history_list}
        run_logger.debug(f"FINAL OUTPUT DANS analysis_runner: {final_output}")
        print(json.dumps(final_output, indent=2))

        return final_output

    except KernelInvokeException as e:
        run_logger.error(f"Erreur d'invocation du Kernel durant l'analyse: {e}", exc_info=True)
        return {"status": "error", "message": f"Kernel Invocation Error: {e}"}
    except Exception as e:
        run_logger.error(f"Erreur générale durant l'analyse: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    finally:
         run_end_time = time.time()
         total_duration = run_end_time - run_start_time
         run_logger.info(f"Fin analyse. Durée totale: {total_duration:.2f} sec.")

         print("\n--- Historique Détaillé de la Conversation ---")
         final_history_messages = []
         if local_group_chat and hasattr(local_group_chat, 'history') and hasattr(local_group_chat.history, 'messages'):
             final_history_messages = local_group_chat.history.messages

         if final_history_messages:
             for msg_idx, msg in enumerate(final_history_messages):
                 author = msg.name or f"Role:{msg.role.name}"
                 role_name = msg.role.name
                 content_display = str(msg.content)[:2000] + "..." if len(str(msg.content)) > 2000 else str(msg.content)
                 print(f"[{msg_idx}] [{author} ({role_name})]: {content_display}")
                 tool_calls = getattr(msg, 'tool_calls', []) or []
                 if tool_calls:
                     print("   Tool Calls:")
                     for tc_idx, tc in enumerate(tool_calls):
                         plugin_name, func_name = 'N/A', 'N/A'
                         function_name_attr = getattr(getattr(tc, 'function', None), 'name', None)
                         if function_name_attr and isinstance(function_name_attr, str) and '-' in function_name_attr:
                             parts = function_name_attr.split('-', 1)
                             if len(parts) == 2: plugin_name, func_name = parts
                         args_dict = getattr(getattr(tc, 'function', None), 'arguments', {}) or []
                         args_str = json.dumps(args_dict) if args_dict else "{}"
                         args_display = args_str[:200] + "..." if len(args_str) > 200 else args_str
                         print(f"     [{tc_idx}] - {plugin_name}-{func_name}({args_display})")
         else:
             print("(Historique final vide ou inaccessible)")
         print("----------------------------------------------\n")

         if 'raw_logger_hook' in locals() and hasattr(llm_service, "remove_chat_hook_handler"):
             try:
                 llm_service.remove_chat_hook_handler(raw_logger_hook)
                 run_logger.info("RawResponseLogger hook retiré du service LLM.")
             except Exception as e_rm_hook:
                 run_logger.warning(f"Erreur lors du retrait du RawResponseLogger hook: {e_rm_hook}")

         print("=========================================")
         print(f"== Fin de l'Analyse Collaborative (Durée: {total_duration:.2f}s) ==")
         print("=========================================")
         
         print("\n--- État Final de l'Analyse (Instance Locale) ---")
         if local_state:
             try: print(local_state.to_json(indent=2))
             except Exception as e_json: print(f"(Erreur sérialisation état final: {e_json})"); print(f"Repr: {repr(local_state)}")
         else: print("(Instance état locale non disponible)")

         jvm_status = "(JVM active)" if ('jpype' in globals() and jpype.isJVMStarted()) else "(JVM non active)"
         print(f"\n{jvm_status}")
         run_logger.info(f"État final JVM: {jvm_status}")
         run_logger.info(f"--- Fin Run_{run_id} ---")

class AnalysisRunner:
   def __init__(self, strategy=None):
       self.strategy = strategy
       self.logger = logging.getLogger("AnalysisRunner")
       self.logger.info("AnalysisRunner initialisé.")

   async def run_analysis_async(self, text_content, llm_service=None):
       if llm_service is None:
           from argumentation_analysis.core.llm_service import create_llm_service
           llm_service = create_llm_service()

       self.logger.info(f"Exécution de l'analyse asynchrone sur un texte de {len(text_content)} caractères")

       return await _run_analysis_conversation(
           texte_a_analyser=text_content,
           llm_service=llm_service
       )

def generate_report(analysis_results, output_path=None):
     logger = logging.getLogger("generate_report")
     if output_path is None:
         timestamp = time.strftime("%Y%m%d_%H%M%S")
         output_path = f"rapport_analyse_{timestamp}.json"
     output_dir = os.path.dirname(output_path)
     if output_dir and not os.path.exists(output_dir):
         os.makedirs(output_dir, exist_ok=True)
     report_data = {
         "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
         "analysis_results": analysis_results,
         "metadata": {"generator": "AnalysisRunner", "version": "1.0"}
     }
     try:
         with open(output_path, 'w', encoding='utf-8') as f:
             json.dump(report_data, f, indent=2, ensure_ascii=False)
         logger.info(f"Rapport généré: {output_path}")
         return output_path
     except Exception as e:
         logger.error(f"Erreur lors de la génération du rapport: {e}")
         raise

if __name__ == "__main__":
     import argparse
     parser = argparse.ArgumentParser(description="Exécute l'analyse d'argumentation sur un texte donné.")
     group = parser.add_mutually_exclusive_group(required=True)
     group.add_argument("--text", type=str, help="Le texte à analyser directement.")
     group.add_argument("--file-path", type=str, help="Chemin vers le fichier texte à analyser.")
     args = parser.parse_args()

     if not logging.getLogger().handlers:
         logging.basicConfig(level=logging.INFO,
                             format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                             datefmt='%Y-%m-%d %H:%M:%S')

     runner_logger = logging.getLogger("AnalysisRunnerCLI")

     text_to_analyze = ""
     if args.text:
         text_to_analyze = args.text
         runner_logger.info(f"Lancement de AnalysisRunner en mode CLI pour le texte fourni (début) : \"{text_to_analyze[:100]}...\"")
     elif args.file_path:
         runner_logger.info(f"Lancement de AnalysisRunner en mode CLI pour le fichier : \"{args.file_path}\"")
         try:
             with open(args.file_path, 'r', encoding='utf-8') as f:
                 text_to_analyze = f.read()
             runner_logger.info(f"Contenu du fichier '{args.file_path}' lu (longueur: {len(text_to_analyze)}).")
             if not text_to_analyze.strip():
                  runner_logger.error(f"Le fichier {args.file_path} est vide ou ne contient que des espaces.")
                  sys.exit(1)
         except FileNotFoundError:
             runner_logger.error(f"Fichier non trouvé : {args.file_path}")
             sys.exit(1)
         except Exception as e:
             runner_logger.error(f"Erreur lors de la lecture du fichier {args.file_path}: {e}", exc_info=True)
             sys.exit(1)
     
     from argumentation_analysis.core.llm_service import create_llm_service
     
     try:
         runner_logger.info("Initialisation explicite de la JVM depuis analysis_runner...")
         jvm_ready = initialize_jvm(lib_dir_path=str(LIBS_DIR))
         if not jvm_ready:
             runner_logger.error("Échec de l'initialisation de la JVM. L'agent PL et d'autres fonctionnalités Java pourraient ne pas fonctionner.")
         else:
             runner_logger.info("JVM initialisée avec succès (ou déjà prête).")

         llm_service_instance = create_llm_service()
         asyncio.run(_run_analysis_conversation(texte_a_analyser=text_to_analyze, llm_service=llm_service_instance))
         runner_logger.info("Analyse terminée avec succès.")
     except Exception as e:
         runner_logger.error(f"Une erreur est survenue lors de l'exécution de l'analyse : {e}", exc_info=True)
         print(f"ERREUR CLI: {e}")
         traceback.print_exc()
