RAID: Shadow Legends – Siege Defense Assignment Helper
======================================================
Author: LittleHeap (discord: wolus6075)

This is a small helper tool for clan leaders/officers in RAID: Shadow Legends.
It assigns players’ defense teams to Siege positions based on:

- position conditions (faction / role / affinity / rarity…),
- position priority (must-have / important / nice-to-have),
- team power,
- max number of positions per player.

It uses a simple optimization model (ILP with `pulp`) to find a good global assignment.

The tool runs locally, does not connect to the internet or RAID API, and only reads your local CSV/JSON files.


1. Requirements
===============

- Python 3.8+ installed
- Python packages:
  pip install pulp

That’s it – no admin rights or extra tools needed.


2. Files
========

You should have these files in one folder:

- raid_siege_gui.py – the main script with the GUI
- config.json – configuration (restrictions, priorities, factions, etc.)
- your input files:
  - Players.csv
  - Positions.csv

You can rename the CSV files; the GUI lets you browse for any file.


3. Input File Formats
=====================

3.1 Players.csv
---------------

Example:

player_name,condition_type,power  
LittleHeap,Lizardmen,3  
Ntt,Sacred Order,3  
Thorndill,High Elves,2  

Columns:

- player_name – player nickname
- condition_type – description of the kind of team this player can place  
  (e.g. "Lizardmen", "Sacred Order", "HP", etc.)
- power – team strength on a small scale (e.g. 1 = average, 2 = good, 3 = strong)

Each row represents one possible defense team this player can use.


3.2 Positions.csv
------------------

Example:

position_id,condition1,condition2,condition3  
5,Lizardmen only,Sacred Order only,HP only  
11,Lizardmen only,HP only,Spirit  
13,Sacred Order only,Attack,Rare only  

Columns:

- position_id – Siege position ID (should match IDs used in config.json priorities)
- condition1, condition2, condition3 – three conditions for that position  
  (e.g. "Lizardmen", "HP", "Spirit", "Rare", etc.)

The script tries to match each team’s condition_type to one of these three conditions.


3.3 config.json
----------------

Example (shortened):

{
  "MaxPositionsPerPlayer": 2,
  "Restrictions": {
    "10": "Factions",
    "9": "Rare",
    "8": "Role",
    "7": "Epic",
    "6": "Union",
    "5": "Affinity",
    "4": "Void",
    "3": "Legendary",
    "1": "Others"
  },
  "PositionsPriority": {
    "3": [5, 3, 2, 15],
    "2": [8, 10, 7, 12, 11],
    "1": [16, 13, 14, 17]
  },
  "RestrictionWeights": {
    "Factions": 10,
    "Rare": 9,
    "Role": 8,
    "Epic": 7,
    "Union": 6,
    "Affinity": 5,
    "Void": 4,
    "Legendary": 3,
    "Others": 1
  },
  "Factions": [
    "Bannerlords",
    "High Elves",
    "Sacred Order",
    "Barbarians",
    "Ogryn Tribes",
    "Lizardmen",
    "Skinwalkers",
    "Orcs",
    "Demonspawn",
    "Undead Hordes",
    "Dark Elves",
    "Knight Revenant",
    "Dwarves",
    "Shadowkin",
    "Sylvan Watchers",
    "Argonites"
  ],
  "Roles": ["HP", "Atk", "Def", "Support"],
  "Unions": {
    "Relerian league": [
      "Bannerlords",
      "High Elves",
      "Sacred Order",
      "Barbarians"
    ],
    "Gaellen Pact": [
      "Ogryn Tribes",
      "Lizardmen",
      "Skinwalkers",
      "Orcs"
    ],
    "The Corrupted": [
      "Demonspawn",
      "Undead Hordes",
      "Dark Elves",
      "Knight Revenant"
    ],
    "Nyresan Union": [
      "Dwarves",
      "Shadowkin",
      "Sylvan Watchers",
      "Argonites"
    ]
  },
  "Affinities": ["Spirit", "Force", "Magic"],
  "VoidAffinity": "Void"
}

Key parts:

- MaxPositionsPerPlayer – hard cap on how many positions one player can get.
- PositionsPriority – which positions are:
  - 3 = must-have
  - 2 = important
  - 1 = nice-to-have
- RestrictionWeights – how “valuable” different restriction types are.
- Factions, Roles, Unions, Affinities, VoidAffinity – used to classify conditions.

You can tune this file without changing the Python code.


4. How Matching Works (simplified)
==================================

For each pair (team, position):

1. Check if the team’s condition_type matches any of the three position conditions  
   (simple text/substring matching, e.g. "Lizardmen only" matches "Lizardmen only",  
   "HP only" matches "HP").
2. If it matches, compute a score:
   - based on restriction type weight (faction / role / affinity / etc.),
   - team power,
   - position priority.

Then the script builds an optimization model that:

- maximizes total score,
- ensures:
  - each position has at most one team,
  - each team is used at most once,
  - each player is assigned to at most MaxPositionsPerPlayer positions.

Result: a globally optimized assignment.


5. How to Run
=============

1. Install Python (if you don’t have it yet).
2. Install pulp:

   pip install pulp

3. Put raid_siege.py, config.json, Players.csv, Positions.csv in one folder.
4. Run the GUI:

   python raid_siege.py (or just double click if you have Python installed correctly)

5. In the window:
   - Click “Browse” next to Players.csv and select your players file.
   - Click “Browse” next to Positions.csv and select your positions file.
   - Click “Browse” next to config.json and select the config file.
   - Click “Run Assignment”.

6. The “Assignments” text box will show lines like:

   Position 5: Ntt (team condition: Sacred Order)  
   Position 11: LittleHeap (team condition: Lizardmen)

You can copy this text into Discord or wherever you coordinate your clan defenses.


7. Troubleshooting
==================

- Window does not open / Python not found  
  - Make sure Python is installed and on your PATH.  
  - Try `python3 raid_siege.py` instead of `python` on some systems.

- Error: module 'pulp' not found  
  - Install pulp:  
    pip install pulp
