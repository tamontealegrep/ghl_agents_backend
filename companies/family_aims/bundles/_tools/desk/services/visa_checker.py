import re

from ..schemas.visa import VisaCheckResponse


class VisaCheckerService:
    def __init__(self):
        # Listas basadas en la solicitud del usuario
        self.required_countries = {
            "AFGHANISTAN", "AFG", "ANGOLA", "AGO", "SAUDI ARABIA", "SAU", "ALGERIA", "DZA", "ARMENIA", "ARM",
            "BAHRAIN", "BHR", "BANGLADESH", "BGD", "BENIN", "BEN", "BOTSWANA", "BWA", "BURKINA FASO", "BFA",
            "BURUNDI", "BDI", "BHUTAN", "BTN", "CAPE VERDE", "CPV", "CAMEROON", "CMR", "CHAD", "TCD", "CONGO", "COG",
            "DEMOCRATIC REPUBLIC OF THE CONGO", "COD", "NORTH KOREA", "PRK", "IVORY COAST", "CIV", "CUBA", "CUB",
            "DJIBOUTI", "DJI", "EGYPT", "EGY", "ERITREA", "ERI", "ETHIOPIA", "ETH", "GABON", "GAB", "GAMBIA", "GMB",
            "GHANA", "GHA", "GUINEA", "GIN", "GUINEA-BISSAU", "GNB", "EQUATORIAL GUINEA", "GNQ", "HAITI", "HTI",
            "IRAN", "IRN", "IRAQ", "IRQ", "JORDAN", "JOR", "KENYA", "KEN", "KYRGYZSTAN", "KGZ", "KUWAIT", "KWT",
            "KOSOVO", "XKX", "LAOS", "LAO", "LESOTHO", "LSO", "LEBANON", "LBN", "LIBERIA", "LBR", "LIBYA", "LBY",
            "MADAGASCAR", "MDG", "MALAWI", "MWI", "MAURITIUS", "MUS", "MAURITANIA", "MRT", "MOZAMBIQUE", "MOZ",
            "NAMIBIA", "NAM", "NAURU", "NRU", "NEPAL", "NPL", "NIGER", "NER", "NIGERIA", "NGA", "PAKISTAN", "PAK",
            "PALESTINE", "PSE", "CENTRAL AFRICAN REPUBLIC", "CAF", "RWANDA", "RWA", "SAO TOME AND PRINCIPE", "STP",
            "SENEGAL", "SEN", "SIERRA LEONE", "SLE", "SYRIA", "SYR", "SOMALIA", "SOM", "SRI LANKA", "LKA",
            "SOUTH AFRICA", "ZAF", "SUDAN", "SDN", "SOUTH SUDAN", "SSD", "TANZANIA", "TZA", "TAJIKISTAN", "TJK",
            "TIMOR-LESTE", "TLS", "TOGO", "TGO", "TONGA", "TON", "TUNISIA", "TUN", "TURKMENISTAN", "TKM", "TUVALU", "TUV",
            "UGANDA", "UGA", "UZBEKISTAN", "UZB", "VANUATU", "VUT", "YEMEN", "YEM", "ZAMBIA", "ZMB", "ZIMBABWE", "ZWE"
        }

        self.no_visa_countries = {
            "COLOMBIA", "COL", "ALBANIA", "ALB", "ALEMANIA", "GERMANY", "DEU", "ANDORRA", "AND", "ANTIGUA Y BARBUDA", "ANTIGUA AND BARBUDA", "ATG",
            "ARGENTINA", "ARG", "AUSTRALIA", "AUS", "AUSTRIA", "AUT", "AZERBAIYAN", "AZERBAIJAN", "AZE", "BAHAMAS", "BHS",
            "BARBADOS", "BRB", "BELGICA", "BELGIUM", "BEL", "BELICE", "BELIZE", "BLZ", "BOLIVIA", "BOL",
            "BOSNIA Y HERZEGOVINA", "BOSNIA AND HERZEGOVINA", "BIH", "BRASIL", "BRAZIL", "BRA",
            "BRUNEI-DARUSSALAM", "BRUNEI DARUSSALAM", "BRN", "BULGARIA", "BGR", "CANADA", "CAN",
            "REPUBLICA CHECA", "CZECH REPUBLIC", "CZE", "CHILE", "CHL", "CHIPRE", "CYPRUS", "CYP",
            "COREA DEL SUR", "SOUTH KOREA", "KOR", "COSTA RICA", "CRI", "CROACIA", "CROATIA", "HRV", "DINAMARCA", "DENMARK", "DNK",
            "DOMINICA", "DMA", "ECUADOR", "ECU", "EL SALVADOR", "SLV", "EMIRATOS ARABES UNIDOS", "UNITED ARAB EMIRATES", "ARE",
            "ESLOVAQUIA", "SLOVAKIA", "SVK", "ESLOVENIA", "SLOVENIA", "SVN", "ESPANA", "SPAIN", "ESP",
            "ESTADOS UNIDOS", "UNITED STATES", "USA", "ESTONIA", "EST", "FIYI", "FIJI", "FJI", "FILIPINAS", "PHILIPPINES", "PHL",
            "FINLANDIA", "FINLAND", "FIN", "FRANCIA", "FRANCE", "FRA", "GEORGIA", "GEO", "GRANADA", "GRENADA", "GRD",
            "GRECIA", "GREECE", "GRC", "GUATEMALA", "GTM", "GUYANA", "GUY", "HONDURAS", "HND", "HUNGRIA", "HUNGARY", "HUN",
            "INDONESIA", "IDN", "IRLANDA", "IRELAND", "IRL", "ISLANDIA", "ICELAND", "ISL", "ISLAS MARSHALL", "MARSHALL ISLANDS", "MHL",
            "ISLAS SALOMON", "SOLOMON ISLANDS", "SLB", "ITALIA", "ITALY", "ITA", "JAMAICA", "JAM", "JAPON", "JAPAN", "JPN",
            "KAZAJISTAN", "KAZAKHSTAN", "KAZ", "LETONIA", "LATVIA", "LVA", "LIECHTENSTEIN", "LIE", "LITUANIA", "LITHUANIA", "LTU",
            "LUXEMBURGO", "LUXEMBOURG", "LUX", "MACEDONIA DEL NORTE", "NORTH MACEDONIA", "MKD", "MALTA", "MLT",
            "MARRUECOS", "MOROCCO", "MAR", "MEXICO", "MEX", "MICRONESIA", "FSM", "MOLDOVA", "MDA", "MONACO", "MCO",
            "MONTENEGRO", "MNE", "NORUEGA", "NORWAY", "NOR", "NUEVA ZELANDA", "NEW ZEALAND", "NZL", "PAISES BAJOS", "NETHERLANDS", "NLD",
            "OMAN", "OMN", "PALAU", "PLW", "PANAMA", "PAN", "PAPUA NUEVA GUINEA", "PAPUA NEW GUINEA", "PNG", "PARAGUAY", "PRY",
            "PERU", "PER", "POLONIA", "POLAND", "POL", "PORTUGAL", "PRT", "CATAR", "QATAR", "QAT", "REINO UNIDO", "UNITED KINGDOM", "GBR",
            "REPUBLICA DOMINICANA", "DOMINICAN REPUBLIC", "DOM", "RUMANIA", "ROMANIA", "ROU", "RUSIA", "RUSSIA", "RUS",
            "SAN CRISTOBAL Y NIEVES", "SAINT KITTS AND NEVIS", "KNA", "SAMOA", "WSM", "SAN MARINO", "SMR",
            "SANTA LUCIA", "SAINT LUCIA", "LCA", "SANTA SEDE", "HOLY SEE", "VAT", "SAN VICENTE Y LAS GRANADINAS", "SAINT VINCENT AND THE GRENADINES", "VCT",
            "SERBIA", "SRB", "SINGAPUR", "SINGAPORE", "SGP", "SUECIA", "SWEDEN", "SWE", "SUIZA", "SWITZERLAND", "CHE",
            "SURINAM", "SURINAME", "SUR", "TRINIDAD Y TOBAGO", "TRINIDAD AND TOBAGO", "TTO", "TURQUIA", "TURKEY", "TUR",
            "UCRANIA", "UKRAINE", "UKR", "URUGUAY", "URY", "VENEZUELA", "VEN"
        }

        self.conditional_countries = {
            "CAMBOYA", "CAMBODIA", "KHM", "CHINA", "CHN", "INDIA", "IND", "MYANMAR", "MMR", "NICARAGUA", "NIC",
            "TAILANDIA", "THAILAND", "THA", "VIETNAM", "VNM"
        }

    def normalize_string(self, text: str) -> str:
        # Quitar espacios múltiples, espacios al inicio/final y convertir a mayúsculas
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)
        text = text.upper()
        # Quitar acentos básicos
        text = re.sub(r'[ÁÀÄÂ]', 'A', text)
        text = re.sub(r'[ÉÈËÊ]', 'E', text)
        text = re.sub(r'[ÍÌÏÎ]', 'I', text)
        text = re.sub(r'[ÓÒÖÔ]', 'O', text)
        text = re.sub(r'[ÚÙÜÛ]', 'U', text)
        text = re.sub(r'[Ñ]', 'N', text)
        return text

    def check_visas(self, nationalities: str | list[str]) -> VisaCheckResponse:
        try:
            if isinstance(nationalities, str):
                # Dividir por comas y limpiar espacios de cada elemento
                nationalities_list = [n.strip() for n in nationalities.split(",") if n.strip()]
            else:
                nationalities_list = [n.strip() for n in nationalities if isinstance(n, str) and n.strip()]

            if not nationalities_list:
                return VisaCheckResponse(
                    success=False,
                    nationality="",
                    requires_visa=True,
                    conditional_visa=False,
                    summary="No se proporcionaron nacionalidades válidas.",
                    errors="Empty nationality list"
                )

            individual_results = []
            cleaned_nationalities = []

            for nation in nationalities_list:
                # Limpiar espacios internos múltiples para la visualización
                cleaned_nation = re.sub(r'\s+', ' ', nation).strip()
                cleaned_nationalities.append(cleaned_nation)
                
                norm_nation = self.normalize_string(nation)
                
                if norm_nation in self.no_visa_countries:
                    individual_results.append({"req": False, "cond": False, "status": "No requiere visa", "name": cleaned_nation})
                elif norm_nation in self.conditional_countries:
                    individual_results.append({"req": True, "cond": True, "status": "Requiere visa (Condicional)", "name": cleaned_nation})
                elif norm_nation in self.required_countries:
                    individual_results.append({"req": True, "cond": False, "status": "Requiere visa", "name": cleaned_nation})
                else:
                    individual_results.append({"req": True, "cond": False, "status": "Requiere visa (No encontrada)", "name": cleaned_nation})

            # Lógica de agregación: 
            # 1. Si alguna nacionalidad permite entrar SIN visa, la persona NO requiere visa.
            # 2. Si ninguna permite entrar sin visa, pero alguna es condicional, es condicional.
            # 3. De lo contrario, requiere visa.
            
            final_requires = True
            final_conditional = False
            
            if any(not res["req"] for res in individual_results):
                final_requires = False
                final_conditional = False
            elif any(res["cond"] for res in individual_results):
                final_requires = True
                final_conditional = True
            else:
                final_requires = True
                final_conditional = False

            # Generar resumen con nombres limpios
            summary_parts = [f"{res['name']}: {res['status']}" for res in individual_results]
            summary = "Resultados: " + " | ".join(summary_parts)
            nationality_output = ", ".join(cleaned_nationalities)

            return VisaCheckResponse(
                success=True,
                nationality=nationality_output,
                requires_visa=final_requires,
                conditional_visa=final_conditional,
                summary=summary,
                errors=None
            )
        except Exception as e:
            return VisaCheckResponse(
                success=False,
                nationality="",
                requires_visa=True,
                conditional_visa=False,
                summary="Error procesando la solicitud.",
                errors=str(e)
            )
