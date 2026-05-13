# Skill: executor
**Purpose**: To perform sandboxed execution of subtasks and code as defined by the orchestrator.

## Trigger
 * Receipt of a specific task ID from the core/dag_engine.py.
 *  * Dependencies from the research_brief skill are fully resolved.
  
    * ## Inputs
    *  * **Outcome Spec**: Structured parameters defining the required task output.
       *  * **Task Parameters**: Specific variables, code snippets, or environment requirements.
        
          * ## Outputs
          *  * **Raw Task Output**: Unverified data, logs, or file artifacts generated during execution.
             *  * **Execution Logs**: A trace of the operations performed within the sandbox.
              
                * ## Constraints
                *  * **Stateless by Default**: No data persists within the executor once the task is complete.
                   *  * **Sandboxed Environment**: All execution must occur within isolated filesystem or browser instances.
                      *  * **No Direct Production Access**: All side effects must be forced through explicit artifact writes or approved connectors.
                       
                         * ## Handoff Rules
                         *  * **Success**: On successful execution, hand off the raw output to the verifier skill.
                            *  * **Failure**: If a logic conflict or environment error occurs, return a failure state to the Core Engine for re-routing or "Decay".
