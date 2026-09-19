"""Hard-coded Kenyan electoral geography reference data for ETVS.

Source basis:
- IEBC delimitation materials and 2022 Gazette data.
- Constituency names/counts cross-checked against the public constituency list.
This is intentionally static for the current project phase. It is reference
data, not a substitute for future election-specific gazette ingestion.
"""

REGIONS = {
    "REG-01": "Nairobi",
    "REG-02": "Central",
    "REG-03": "Coast",
    "REG-04": "Eastern",
    "REG-05": "North Eastern",
    "REG-06": "Nyanza",
    "REG-07": "Rift Valley",
    "REG-08": "Western",
}

# county_id, county_code, county_name, region_id
COUNTIES = (
    ("KE-001", "001", "Mombasa", "REG-03"),
    ("KE-002", "002", "Kwale", "REG-03"),
    ("KE-003", "003", "Kilifi", "REG-03"),
    ("KE-004", "004", "Tana River", "REG-03"),
    ("KE-005", "005", "Lamu", "REG-03"),
    ("KE-006", "006", "Taita-Taveta", "REG-03"),
    ("KE-007", "007", "Garissa", "REG-05"),
    ("KE-008", "008", "Wajir", "REG-05"),
    ("KE-009", "009", "Mandera", "REG-05"),
    ("KE-010", "010", "Marsabit", "REG-04"),
    ("KE-011", "011", "Isiolo", "REG-04"),
    ("KE-012", "012", "Meru", "REG-04"),
    ("KE-013", "013", "Tharaka-Nithi", "REG-04"),
    ("KE-014", "014", "Embu", "REG-04"),
    ("KE-015", "015", "Kitui", "REG-04"),
    ("KE-016", "016", "Machakos", "REG-04"),
    ("KE-017", "017", "Makueni", "REG-04"),
    ("KE-018", "018", "Nyandarua", "REG-02"),
    ("KE-019", "019", "Nyeri", "REG-02"),
    ("KE-020", "020", "Kirinyaga", "REG-02"),
    ("KE-021", "021", "Murang'a", "REG-02"),
    ("KE-022", "022", "Kiambu", "REG-02"),
    ("KE-023", "023", "Turkana", "REG-07"),
    ("KE-024", "024", "West Pokot", "REG-07"),
    ("KE-025", "025", "Samburu", "REG-07"),
    ("KE-026", "026", "Trans Nzoia", "REG-07"),
    ("KE-027", "027", "Uasin Gishu", "REG-07"),
    ("KE-028", "028", "Elgeyo-Marakwet", "REG-07"),
    ("KE-029", "029", "Nandi", "REG-07"),
    ("KE-030", "030", "Baringo", "REG-07"),
    ("KE-031", "031", "Laikipia", "REG-07"),
    ("KE-032", "032", "Nakuru", "REG-07"),
    ("KE-033", "033", "Narok", "REG-07"),
    ("KE-034", "034", "Kajiado", "REG-07"),
    ("KE-035", "035", "Kericho", "REG-07"),
    ("KE-036", "036", "Bomet", "REG-07"),
    ("KE-037", "037", "Kakamega", "REG-08"),
    ("KE-038", "038", "Vihiga", "REG-08"),
    ("KE-039", "039", "Bungoma", "REG-08"),
    ("KE-040", "040", "Busia", "REG-08"),
    ("KE-041", "041", "Siaya", "REG-06"),
    ("KE-042", "042", "Kisumu", "REG-06"),
    ("KE-043", "043", "Homa Bay", "REG-06"),
    ("KE-044", "044", "Migori", "REG-06"),
    ("KE-045", "045", "Kisii", "REG-06"),
    ("KE-046", "046", "Nyamira", "REG-06"),
    ("KE-047", "047", "Nairobi", "REG-01"),
)

# constituency_number, constituency_name, county_code
CONSTITUENCIES = (
    (1, "Changamwe", "001"), (2, "Jomvu", "001"), (3, "Kisauni", "001"), (4, "Nyali", "001"), (5, "Likoni", "001"), (6, "Mvita", "001"),
    (7, "Msambweni", "002"), (8, "Lunga Lunga", "002"), (9, "Matuga", "002"), (10, "Kinango", "002"),
    (11, "Kilifi North", "003"), (12, "Kilifi South", "003"), (13, "Kaloleni", "003"), (14, "Rabai", "003"), (15, "Ganze", "003"), (16, "Malindi", "003"), (17, "Magarini", "003"),
    (18, "Garsen", "004"), (19, "Galole", "004"), (20, "Bura", "004"),
    (21, "Lamu East", "005"), (22, "Lamu West", "005"),
    (23, "Taveta", "006"), (24, "Wundanyi", "006"), (25, "Mwatate", "006"), (26, "Voi", "006"),
    (27, "Garissa Township", "007"), (28, "Balambala", "007"), (29, "Lagdera", "007"), (30, "Dadaab", "007"), (31, "Fafi", "007"), (32, "Ijara", "007"),
    (33, "Wajir North", "008"), (34, "Wajir East", "008"), (35, "Tarbaj", "008"), (36, "Wajir West", "008"), (37, "Eldas", "008"), (38, "Wajir South", "008"),
    (39, "Mandera West", "009"), (40, "Banissa", "009"), (41, "Mandera North", "009"), (42, "Mandera South", "009"), (43, "Mandera East", "009"), (44, "Lafey", "009"),
    (45, "Moyale", "010"), (46, "North Horr", "010"), (47, "Saku", "010"), (48, "Laisamis", "010"),
    (49, "Isiolo North", "011"), (50, "Isiolo South", "011"),
    (51, "Igembe South", "012"), (52, "Igembe Central", "012"), (53, "Igembe North", "012"), (54, "Tigania West", "012"), (55, "Tigania East", "012"), (56, "North Imenti", "012"), (57, "Buuri", "012"), (58, "Central Imenti", "012"), (59, "South Imenti", "012"),
    (60, "Maara", "013"), (61, "Chuka/Igambang'ombe", "013"), (62, "Tharaka", "013"),
    (63, "Manyatta", "014"), (64, "Runyenjes", "014"), (65, "Mbeere South", "014"), (66, "Mbeere North", "014"),
    (67, "Mwingi North", "015"), (68, "Mwingi West", "015"), (69, "Mwingi Central", "015"), (70, "Kitui West", "015"), (71, "Kitui Rural", "015"), (72, "Kitui Central", "015"), (73, "Kitui East", "015"), (74, "Kitui South", "015"),
    (75, "Masinga", "016"), (76, "Yatta", "016"), (77, "Kangundo", "016"), (78, "Matungulu", "016"), (79, "Kathiani", "016"), (80, "Mavoko", "016"), (81, "Machakos Town", "016"), (82, "Mwala", "016"),
    (83, "Mbooni", "017"), (84, "Kilome", "017"), (85, "Kaiti", "017"), (86, "Makueni", "017"), (87, "Kibwezi West", "017"), (88, "Kibwezi East", "017"),
    (89, "Kinangop", "018"), (90, "Kipipiri", "018"), (91, "Ol Kalou", "018"), (92, "Ol Jorok", "018"), (93, "Ndaragwa", "018"),
    (94, "Tetu", "019"), (95, "Kieni", "019"), (96, "Mathira", "019"), (97, "Othaya", "019"), (98, "Mukurweini", "019"), (99, "Nyeri Town", "019"),
    (100, "Mwea", "020"), (101, "Gichugu", "020"), (102, "Ndia", "020"), (103, "Kirinyaga Central", "020"),
    (104, "Kangema", "021"), (105, "Mathioya", "021"), (106, "Kiharu", "021"), (107, "Kigumo", "021"), (108, "Maragwa", "021"), (109, "Kandara", "021"), (110, "Gatanga", "021"),
    (111, "Gatundu South", "022"), (112, "Gatundu North", "022"), (113, "Juja", "022"), (114, "Thika Town", "022"), (115, "Ruiru", "022"), (116, "Githunguri", "022"), (117, "Kiambu", "022"), (118, "Kiambaa", "022"), (119, "Kabete", "022"), (120, "Kikuyu", "022"), (121, "Limuru", "022"), (122, "Lari", "022"),
    (123, "Turkana North", "023"), (124, "Turkana West", "023"), (125, "Turkana Central", "023"), (126, "Loima", "023"), (127, "Turkana South", "023"), (128, "Turkana East", "023"),
    (129, "Kapenguria", "024"), (130, "Sigor", "024"), (131, "Kacheliba", "024"), (132, "Pokot South", "024"),
    (133, "Samburu West", "025"), (134, "Samburu North", "025"), (135, "Samburu East", "025"),
    (136, "Kwanza", "026"), (137, "Endebess", "026"), (138, "Saboti", "026"), (139, "Kiminini", "026"), (140, "Cherangany", "026"),
    (141, "Soy", "027"), (142, "Turbo", "027"), (143, "Moiben", "027"), (144, "Ainabkoi", "027"), (145, "Kapseret", "027"), (146, "Kesses", "027"),
    (147, "Marakwet East", "028"), (148, "Marakwet West", "028"), (149, "Keiyo North", "028"), (150, "Keiyo South", "028"),
    (151, "Tinderet", "029"), (152, "Aldai", "029"), (153, "Nandi Hills", "029"), (154, "Chesumei", "029"), (155, "Emgwen", "029"), (156, "Mosop", "029"),
    (157, "Tiaty", "030"), (158, "Baringo North", "030"), (159, "Baringo Central", "030"), (160, "Baringo South", "030"), (161, "Mogotio", "030"), (162, "Eldama Ravine", "030"),
    (163, "Laikipia West", "031"), (164, "Laikipia East", "031"), (165, "Laikipia North", "031"),
    (166, "Molo", "032"), (167, "Njoro", "032"), (168, "Naivasha", "032"), (169, "Gilgil", "032"), (170, "Kuresoi South", "032"), (171, "Kuresoi North", "032"), (172, "Subukia", "032"), (173, "Rongai", "032"), (174, "Bahati", "032"), (175, "Nakuru Town West", "032"), (176, "Nakuru Town East", "032"),
    (177, "Kilgoris", "033"), (178, "Emurua Dikirr", "033"), (179, "Narok North", "033"), (180, "Narok East", "033"), (181, "Narok South", "033"), (182, "Narok West", "033"),
    (183, "Kajiado North", "034"), (184, "Kajiado Central", "034"), (185, "Kajiado East", "034"), (186, "Kajiado West", "034"), (187, "Kajiado South", "034"),
    (188, "Kipkelion East", "035"), (189, "Kipkelion West", "035"), (190, "Ainamoi", "035"), (191, "Bureti", "035"), (192, "Belgut", "035"), (193, "Sigowet-Soin", "035"),
    (194, "Sotik", "036"), (195, "Chepalungu", "036"), (196, "Bomet East", "036"), (197, "Bomet Central", "036"), (198, "Konoin", "036"),
    (199, "Lugari", "037"), (200, "Likuyani", "037"), (201, "Malava", "037"), (202, "Lurambi", "037"), (203, "Navakholo", "037"), (204, "Mumias West", "037"), (205, "Mumias East", "037"), (206, "Matungu", "037"), (207, "Butere", "037"), (208, "Khwisero", "037"), (209, "Shinyalu", "037"), (210, "Ikolomani", "037"),
    (211, "Vihiga", "038"), (212, "Sabatia", "038"), (213, "Hamisi", "038"), (214, "Luanda", "038"), (215, "Emuhaya", "038"),
    (216, "Mount Elgon", "039"), (217, "Sirisia", "039"), (218, "Kabuchai", "039"), (219, "Bumula", "039"), (220, "Kanduyi", "039"), (221, "Webuye East", "039"), (222, "Webuye West", "039"), (223, "Kimilili", "039"), (224, "Tongaren", "039"),
    (225, "Teso North", "040"), (226, "Teso South", "040"), (227, "Nambale", "040"), (228, "Matayos", "040"), (229, "Butula", "040"), (230, "Funyula", "040"), (231, "Budalangi", "040"),
    (232, "Ugenya", "041"), (233, "Ugunja", "041"), (234, "Alego Usonga", "041"), (235, "Gem", "041"), (236, "Bondo", "041"), (237, "Rarieda", "041"),
    (238, "Kisumu East", "042"), (239, "Kisumu West", "042"), (240, "Kisumu Central", "042"), (241, "Seme", "042"), (242, "Nyando", "042"), (243, "Muhoroni", "042"), (244, "Nyakach", "042"),
    (245, "Kasipul", "043"), (246, "Kabondo Kasipul", "043"), (247, "Karachuonyo", "043"), (248, "Rangwe", "043"), (249, "Homa Bay Town", "043"), (250, "Ndhiwa", "043"), (251, "Suba North", "043"), (252, "Suba South", "043"),
    (253, "Rongo", "044"), (254, "Awendo", "044"), (255, "Suna East", "044"), (256, "Suna West", "044"), (257, "Uriri", "044"), (258, "Nyatike", "044"), (259, "Kuria West", "044"), (260, "Kuria East", "044"),
    (261, "Bonchari", "045"), (262, "South Mugirango", "045"), (263, "Bomachoge Borabu", "045"), (264, "Bobasi", "045"), (265, "Bomachoge Chache", "045"), (266, "Nyaribari Masaba", "045"), (267, "Nyaribari Chache", "045"), (268, "Kitutu Chache North", "045"), (269, "Kitutu Chache South", "045"),
    (270, "Kitutu Masaba", "046"), (271, "West Mugirango", "046"), (272, "North Mugirango", "046"), (273, "Borabu", "046"),
    (274, "Westlands", "047"), (275, "Dagoretti North", "047"), (276, "Dagoretti South", "047"), (277, "Lang'ata", "047"), (278, "Kibra", "047"), (279, "Roysambu", "047"), (280, "Kasarani", "047"), (281, "Ruaraka", "047"), (282, "Embakasi South", "047"), (283, "Embakasi North", "047"), (284, "Embakasi Central", "047"), (285, "Embakasi East", "047"), (286, "Embakasi West", "047"), (287, "Makadara", "047"), (288, "Kamukunji", "047"), (289, "Starehe", "047"), (290, "Mathare", "047"),
)

if len(COUNTIES) != 47:
    raise RuntimeError(f"Expected 47 counties, got {len(COUNTIES)}")
if len(CONSTITUENCIES) != 290:
    raise RuntimeError(f"Expected 290 constituencies, got {len(CONSTITUENCIES)}")
if len({n for n, _, _ in CONSTITUENCIES}) != 290:
    raise RuntimeError("Constituency numbers must be unique")


# Historical 2022 IEBC diaspora polling-station reference data.
# Source: IEBC "Register of Voters Residing Outside Kenya" / 21 June 2022
# Kenya Gazette. These are historical reference records, not 2027 eligibility.
DIASPORA_STATIONS_2022 = (
    ("048291500000101", "Tanzania", "Kenya Embassy in Dar es Salaam", 496),
    ("048291500000102", "Tanzania", "Kenya Embassy in Dar es Salaam", 496),
    ("048291500002001", "Tanzania", "Kenya Consulate in Arusha", 410),
    ("048291500100301", "Uganda", "Kenya High Commission in Kampala", 471),
    ("048291500100302", "Uganda", "Kenya High Commission in Kampala", 470),
    ("048291500100303", "Uganda", "Kenya High Commission in Kampala", 470),
    ("048291500200401", "Rwanda", "Kenya Embassy in Kigali", 545),
    ("048291500200402", "Rwanda", "Kenya Embassy in Kigali", 545),
    ("048291500300501", "Burundi", "Kenya Embassy in Bujumbura", 201),
    ("048291500400601", "South Africa", "Kenya Embassy in Pretoria", 479),
    ("048291500400602", "South Africa", "Kenya Embassy in Pretoria", 479),
    ("048291500500701", "South Sudan", "Kenya Embassy in Juba", 489),
    ("048291500500702", "South Sudan", "Kenya Embassy in Juba", 488),
    ("048291500600801", "Germany", "Kenya Embassy in Berlin", 314),
    ("048291500700901", "United Kingdom", "Kenya High Commission in London", 399),
    ("048291500700902", "United Kingdom", "Kenya High Commission in London", 399),
    ("048291500801001", "Qatar", "Kenya Embassy in Doha", 479),
    ("048291500801002", "Qatar", "Kenya Embassy in Doha", 479),
    ("048291500801003", "Qatar", "Kenya Embassy in Doha", 479),
    ("048291500901101", "United Arab Emirates", "Kenya Embassy in Abu Dhabi", 103),
    ("048291500901201", "United Arab Emirates", "Kenya Consulate in Dubai", 642),
    ("048291501001301", "Canada", "Kenya High Commission in Ottawa", 112),
    ("048291501001401", "Canada", "Kenya Honorary Consulate in Toronto", 167),
    ("048291501001501", "Canada", "Kenya Honorary Consulate in Vancouver", 87),
    ("048291501101601", "United States of America", "Kenya Embassy in Washington DC", 314),
    ("048291501101701", "United States of America", "Kenya Consulate in New York", 298),
    ("048291501101801", "United States of America", "Kenya Consulate in Los Angeles", 132),
)

if len(DIASPORA_STATIONS_2022) != 27:
    raise RuntimeError(f"Expected 27 2022 diaspora polling stations, got {len(DIASPORA_STATIONS_2022)}")
if sum(voters for _, _, _, voters in DIASPORA_STATIONS_2022) != 10443:
    raise RuntimeError("2022 diaspora station voters must total 10,443")
