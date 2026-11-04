# Lesson migration: before and after

Square-specific lessons rewritten as patterns, with feature tags (ids, stats, source and kind unchanged).

## L001 (opponent_shot, from game 1 move 23)

Tags true at the source position: enemy_piece_attacked_undefended, enemy_piece_on_my_2nd_or_3rd_rank, king_castled_kingside, material_down, my_piece_retreated_recently

| | before | after |
|---|---|---|
| rule | Never leave my queen and a rook both on squares one enemy knight can reach in one move, e.g. Qc3 and Re3 from d5. | When recapturing, pick the piece that keeps my queen and rooks off squares one enemy knight jump can fork, e.g. Rxe3? Nd5 hits Qc3+Re3. |
| trigger | An enemy knight is one move from a square that attacks two of my queen, rooks or king at once. | I can capture an enemy piece on my 2nd or 3rd rank with my queen or a rook, and an enemy knight is one jump from where it could attack two of my queen, rooks or king after the recapture. |
| check | Is there a square the enemy knight can reach next move that attacks my queen and a rook (or king) together? If yes, move one of them off that pattern first. | After my capture, can an enemy knight jump to a square attacking my queen and a rook (or king) together? If yes, recapture with the other piece or move one of them off that pattern. |
| phase | middlegame | middlegame |
| motifs | fork, hanging_piece | fork, hanging_piece |
| features | (none) | enemy_piece_on_my_2nd_or_3rd_rank, enemy_piece_attacked_undefended |

## L002 (mistake, from game 1 move 43)

Tags true at the source position: enemy_knight_near_my_king, material_down, my_king_attacked, my_passed_pawn

| | before | after |
|---|---|---|
| rule | Before moving my king, check it does not stop defending a pawn an enemy knight can capture with check, like Kh2-h1 dropping g3. | Before moving my king, keep it guarding nearby pawns an enemy knight could capture with check, e.g. Kh1 dropping g3. |
| trigger | An enemy knight is within two moves of my king, and my king defends a pawn on g3, f3, g2 or h3. | An enemy knight is near my king, and my king is the only defender of a pawn beside it on my 2nd or 3rd rank. |
| check | After my king move, can an enemy knight capture a pawn or land with check? If yes, choose a different king square or defend that pawn first. | After my king move, can an enemy knight capture a pawn my king stopped guarding, or land with check? If yes, choose a different king square or defend that pawn first. |
| phase | any | any |
| motifs | king_safety, fork | king_safety, fork |
| features | (none) | enemy_knight_near_my_king, my_king_attacked |

## L003 (self_assessment, from game 1 move 8)

Tags true at the source position: king_castled_kingside, my_back_rank_weak

| | before | after |
|---|---|---|
| rule | If a bishop retreats once after an enemy tempo move, like Bb5-e2 after ...a6, set TREND worse and look for e5 or Nxc6. | When an enemy pawn or knight chases my bishop back with tempo, set TREND worse and seek a central pawn break or a trade. |
| trigger | In the last five moves my bishop retreated after an enemy pawn or knight attacked it, while the opponent gained space or developed. | In my last few moves one of my bishops retreated toward my side because an enemy pawn or knight attacked it, while the opponent gained space or developed a piece. |
| check | Did one of my pieces retreat in the last five moves because of an enemy tempo move? If yes, write TREND worse and look for a forcing move like e5, d4 or a trade. | Did one of my pieces retreat recently because an enemy pawn or knight attacked it? If yes, write TREND worse and look first for a forcing central pawn push or a trade of the attacker. |
| phase | opening | opening |
| motifs | self_assessment | self_assessment, piece_activity |
| features | (none) | king_castled_kingside |

## L004 (mistake, from game 2 move 20)

Tags true at the source position: enemy_halfopen_file_to_my_king, enemy_piece_attacked_undefended, king_castled_queenside

| | before | after |
|---|---|---|
| rule | With my king on b1 and an enemy bishop on b4 or queen on a5, play Bd4 or Qe3 to guard b2 and c3 first. | When my king is castled queenside and enemy pieces aim at my 2nd and 3rd rank pawns, guard them (e.g. Bd4, Qe3) before grabbing material. |
| trigger | My king is on b1 or c1, and an enemy bishop on the a5-e1 diagonal or a queen or rook on the a-, b- or c-file targets b2 or c3. | My king is castled queenside, and an enemy bishop on a diagonal toward my king or an enemy queen or rook on a half-open file near my king targets the pawns or squares on my 2nd or 3rd rank in front of it. |
| check | Are b2 and c3 each defended at least as often as Black attacks them after my move? If not, play Bd4, Qe3 or a defending move instead. | After my move, is every pawn and square in front of my queenside king defended at least as often as the enemy attacks it? If not, play a move that adds a defender there instead. |
| phase | middlegame | middlegame |
| motifs | king_safety, prophylaxis | king_safety, prophylaxis |
| features | (none) | king_castled_queenside, enemy_halfopen_file_to_my_king |

## L005 (mistake, from game 2 move 15)

Tags true at the source position: enemy_halfopen_file_to_my_king, enemy_knight_on_rim_trapped, king_castled_queenside, my_rook_on_enemy_bishop_diagonal

| | before | after |
|---|---|---|
| rule | When an enemy knight on h5 or a5 has no safe squares, attack it at once with Be2 or Bh3, not a pawn push. | When an enemy rim knight has no safe squares, attack it immediately with a bishop or pawn, e.g. Bh3, instead of a pawn push elsewhere. |
| trigger | An enemy knight on the rim has every destination square covered by my pieces or pawns. | An enemy knight on the edge of the board has every destination square covered by my pieces or pawns. |
| check | Can a bishop or pawn attack the trapped knight right now? If yes, play that before any other plan move. | Is there an enemy rim knight with no safe square that my bishop or pawn can attack right now? If yes, play that attack before any other plan move. |
| phase | middlegame | middlegame |
| motifs | piece_activity, conversion | piece_activity, conversion |
| features | (none) | enemy_knight_on_rim_trapped |

## L006 (self_assessment, from game 2 move 11)

Tags true at the source position: enemy_halfopen_file_to_my_king, king_castled_queenside, my_back_rank_weak, my_rook_on_enemy_bishop_diagonal

| | before | after |
|---|---|---|
| rule | After castling queenside, count enemy pieces aimed at a2, b2 and c3 each move; if the count rose since my last move, set TREND worse. | With my king castled queenside, count enemy pieces aimed at the squares in front of it each move; if the count rose, set TREND worse. |
| trigger | My king is on b1 or c1, and the enemy has pawns on b5 or a5, or pieces on the a-, b- or c-files. | My king is castled on the queenside, and the enemy has pawns advancing on that wing or pieces on the files on or next to my king's file. |
| check | Is the number of enemy pieces hitting a2, b2 or c3 higher than last move? If yes, write TREND worse and choose a defending move like Bd4 or Qe3. | Do more enemy pieces hit the squares in front of my king than after my last move? If yes, write TREND worse and choose a move that adds a defender to those squares or trades off an attacker, before continuing my own plan. |
| phase | middlegame | middlegame |
| motifs | self_assessment, king_safety | self_assessment, king_safety |
| features | (none) | king_castled_queenside, enemy_halfopen_file_to_my_king |

## L007 (mistake, from game 3 move 22)

Tags true at the source position: enemy_piece_attacked_undefended, king_castled_kingside, my_back_rank_weak, my_piece_attacked_undefended, my_piece_retreated_recently, my_rook_on_enemy_bishop_diagonal, two_plus_open_files

| | before | after |
|---|---|---|
| rule | When my queen on c3 or b2 pins a knight on f6 to the h8 rook, attack f6 again with Bxg5 before retreating any piece. | When my queen pins an enemy knight to its rook, ignore that knight's threats and attack it again, e.g. Bxg5, instead of retreating. |
| trigger | My queen is on the a1-h8 diagonal, an enemy knight on f6 or e5 is the only piece between it and an enemy rook on h8. | My queen stands on a line with exactly one enemy piece between it and an enemy rook; that pinned piece attacks one of my pieces, and another of my pieces can attack the pinned piece this move. |
| check | Is an enemy piece pinned to a rook by my queen, and can I attack it a second time now? If yes, play that attack before any retreat. | Is the enemy piece threatening mine pinned to its rook by my queen? If yes, don't retreat: move another piece to attack the pinned piece, taking a loose pawn on the way if possible. |
| phase | middlegame | middlegame |
| motifs | pin, piece_activity | pin, piece_activity |
| features | (none) | my_piece_attacked_undefended, enemy_piece_attacked_undefended |

## L008 (mistake, from game 3 move 29)

Tags true at the source position: enemy_piece_on_my_2nd_or_3rd_rank, king_castled_kingside, my_back_rank_weak, my_piece_attacked_undefended, my_piece_retreated_recently, my_queen_moved_twice, my_rook_on_enemy_bishop_diagonal, two_plus_open_files

| | before | after |
|---|---|---|
| rule | Before trading queens, move my a1 rook off the long diagonal if an enemy dark bishop on e5 or d4 sees b2. | When my rook sits on an enemy bishop's diagonal behind one undefended pawn, move the rook off before trading queens, e.g. Re1. |
| trigger | My rook is on a1, an enemy bishop is on the a1-h8 diagonal, and only my b2 pawn stands between them. | One of my rooks stands on a diagonal of an enemy bishop, only one of my pawns stands between them, and that pawn is attacked by the bishop and not defended. |
| check | After the trade, can the enemy bishop take b2 and then a1? If yes, play Re1 or Rb1 first. | If I make my planned move (especially a queen trade or pawn grab), can the enemy bishop take that pawn and then win my rook? If yes, first move the rook off the diagonal to an open file. |
| phase | middlegame | middlegame |
| motifs | hanging_piece, pin | hanging_piece, pin |
| features | (none) | my_rook_on_enemy_bishop_diagonal, my_piece_attacked_undefended |

## L009 (self_assessment, from game 3 move 11)

Tags true at the source position: enemy_piece_attacked_undefended, king_castled_kingside, my_back_rank_weak, my_piece_retreated_recently

| | before | after |
|---|---|---|
| rule | If my queen moved twice in a row before move 15 without winning material, set TREND worse and develop a minor piece instead. | In the opening, if my queen has moved repeatedly or retreated without winning material, stop moving it and develop a minor piece or castle. |
| trigger | My queen made the last two moves, it is before move 15, and material is unchanged. | Before move 15, my queen has made two or more of my recent moves or just retreated, material is level, and I still have undeveloped minor pieces or an uncastled king. |
| check | Did my queen move on each of my last two turns without gaining material? If yes, write TREND worse and play a developing or castling move. | Have I spent two or more recent moves on my queen, or retreated it, without gaining material? If yes, write TREND worse and play a developing or castling move instead of another queen move. |
| phase | opening | opening |
| motifs | self_assessment, prophylaxis | self_assessment, piece_activity |
| features | (none) | my_piece_retreated_recently |
