# Skill: verifier
* **Purpose**: Mandatory validation of sandboxed execution results.
* * **Input**: Raw output from the `executor`.
  * * **Output**: Boolean status and cleaned data packet.
    * * **Safety**: Prevents corrupted or unverified data from persisting.
