#!/usr/bin/env python3#!/usr/bin/env python3

"""Test script to verify COMET constraints with 9 eligible people.""""""Test script to verify COMET constraints with 9 eligible people."""        print(f"Total COMET assignments: {cmd_count} CMD + {cmn_count} CMN = {cmd_count + cmn_count}")

        print("Expected for 7-day COMET week: 7 CMD + 7 CMN = 14 total")

from datetime import date, timedelta        

from rostering.models import Person, Config, ProblemInput        # Show ALL COMET assignments across entire period

from rostering.sequential_solver import SequentialSolver        print(f"\nAll COMET assignments across full period ({config.start_date} to {config.end_date}):")

        

def test_comet_with_9_people():        current_day = config.start_date

    """Test COMET stage with 9 eligible people."""        total_cmd = 0

            total_cmn = 0

    # Create 9 COMET-eligible people (like in loadRegistrarSet)        

    people = [        while current_day <= config.end_date:

        Person(id='reg1', name='Mei Yi Goh', grade='Registrar', wte=0.8, comet_eligible=True),            day_str = current_day.isoformat()

        Person(id='reg2', name='David White', grade='Registrar', wte=0.8, comet_eligible=True),            

        Person(id='reg3', name='Nikki Francis', grade='Registrar', wte=0.8, comet_eligible=True),            cmd_people = []

        Person(id='reg4', name='Reuben Firth', grade='Registrar', wte=0.8, comet_eligible=True),            cmn_people = []

        Person(id='reg5', name='Alexander Yule', grade='Registrar', wte=0.6, comet_eligible=False),            

        Person(id='reg6', name='Abdifatah Mohamud', grade='Registrar', wte=1.0, comet_eligible=True),            for person in people:

        Person(id='reg7', name='Hanin El Abbas', grade='Registrar', wte=0.8, comet_eligible=True),                if day_str in result.partial_roster and person.id in result.partial_roster[day_str]:

        Person(id='reg8', name='Sarah Hallet', grade='Registrar', wte=0.6, comet_eligible=False),                    shift = result.partial_roster[day_str][person.id]

        Person(id='reg9', name='Manan Kamboj', grade='Registrar', wte=1.0, comet_eligible=True),                    if shift == 'COMET_DAY':

        Person(id='reg10', name='Mahmoud', grade='Registrar', wte=1.0, comet_eligible=True),                        cmd_people.append(person.name)

        Person(id='reg11', name='Registrar 11', grade='Registrar', wte=1.0, comet_eligible=True),                        total_cmd += 1

    ]                    elif shift == 'COMET_NIGHT':

                            cmn_people.append(person.name)

    # Create configuration with COMET week                        total_cmn += 1

    config = Config(            

        start_date=date(2025, 2, 10),  # Monday - start of COMET week            if cmd_people or cmn_people:

        end_date=date(2025, 2, 23),    # 14 days                cmd_str = f"CMD: {', '.join(cmd_people)}" if cmd_people else "CMD: -"

        bank_holidays=[],                cmn_str = f"CMN: {', '.join(cmn_people)}" if cmn_people else "CMN: -"

        comet_on_weeks=[date(2025, 2, 10)],  # First week is COMET week                is_comet_week = comet_week_start <= current_day <= comet_week_end

        max_day_clinicians=5,                week_marker = " [COMET WEEK]" if is_comet_week else ""

        ideal_weekday_day_clinicians=4,                print(f"  {current_day.strftime('%a %Y-%m-%d')}: {cmd_str} | {cmn_str}{week_marker}")

        min_weekday_day_clinicians=3            

    )            current_day += timedelta(days=1)

            

    # Create problem input        print(f"\nTotal across all days: {total_cmd} CMD + {total_cmn} CMN = {total_cmd + total_cmn}")

    problem = ProblemInput(config=config, people=people)        

            # Validate coverage

    # Create solver        if cmd_count == 7 and cmn_count == 7:

    solver = SequentialSolver(problem)            print("✅ Perfect COMET coverage: exactly 1 CMD + 1 CMN per day during COMET week")

            else:

    print(f"Testing COMET stage with {len(people)} people ({sum(1 for p in people if p.comet_eligible)} COMET-eligible)")            print(f"❌ Incorrect COMET coverage: expected 7 CMD + 7 CMN, got {cmd_count} CMD + {cmn_count} CMN")atetime import date, timedelta

    print(f"COMET week: {config.comet_on_weeks[0]} to {config.comet_on_weeks[0] + timedelta(days=6)}")from rostering.models import Person, Config, ProblemInput

    print(f"Full period: {config.start_date} to {config.end_date}")from rostering.sequential_solver import SequentialSolver

    

    # Solve COMET stagedef test_comet_with_9_people():

    result = solver.solve_stage("comet", timeout_seconds=60)    """Test COMET stage with 9 eligible people."""

        

    print("\nCOMET Stage Result:")    # Create 9 COMET-eligible people (like in loadRegistrarSet)

    print(f"Success: {result.success}")    people = [

    print(f"Message: {result.message}")        Person(id='reg1', name='Mei Yi Goh', grade='Registrar', wte=0.8, comet_eligible=True),

            Person(id='reg2', name='David White', grade='Registrar', wte=0.8, comet_eligible=True),

    if result.success:        Person(id='reg3', name='Nikki Francis', grade='Registrar', wte=0.8, comet_eligible=True),

        # Count COMET assignments        Person(id='reg4', name='Reuben Firth', grade='Registrar', wte=0.8, comet_eligible=True),

        cmd_count = 0        Person(id='reg5', name='Alexander Yule', grade='Registrar', wte=0.6, comet_eligible=False),

        cmn_count = 0        Person(id='reg6', name='Abdifatah Mohamud', grade='Registrar', wte=1.0, comet_eligible=True),

                Person(id='reg7', name='Hanin El Abbas', grade='Registrar', wte=0.8, comet_eligible=True),

        # Analyze by day        Person(id='reg8', name='Sarah Hallet', grade='Registrar', wte=0.6, comet_eligible=False),

        comet_week_start = date(2025, 2, 10)  # Monday        Person(id='reg9', name='Manan Kamboj', grade='Registrar', wte=1.0, comet_eligible=True),

        comet_week_end = comet_week_start + timedelta(days=6)  # Sunday        Person(id='reg10', name='Mahmoud', grade='Registrar', wte=1.0, comet_eligible=True),

                Person(id='reg11', name='Registrar 11', grade='Registrar', wte=1.0, comet_eligible=True),

        print(f"\nDaily COMET coverage during COMET week ({comet_week_start} to {comet_week_end}):")    ]

            

        current_day = config.start_date    # Create configuration with COMET week

        while current_day <= config.end_date:    config = Config(

            day_str = current_day.isoformat()        start_date=date(2025, 2, 10),  # Monday - start of COMET week

                    end_date=date(2025, 2, 23),    # 14 days

            # Check if this day is in COMET week        bank_holidays=[],

            is_comet_day = comet_week_start <= current_day <= comet_week_end        comet_on_weeks=[date(2025, 2, 10)],  # First week is COMET week

                    max_day_clinicians=5,

            if is_comet_day:        ideal_weekday_day_clinicians=4,

                cmd_people = []        min_weekday_day_clinicians=3

                cmn_people = []    )

                    

                for person in people:    # Create problem input

                    if day_str in result.partial_roster and person.id in result.partial_roster[day_str]:    problem = ProblemInput(config=config, people=people)

                        shift = result.partial_roster[day_str][person.id]    

                        if shift == 'COMET_DAY':    # Create solver

                            cmd_people.append(person.name)    solver = SequentialSolver(problem)

                            cmd_count += 1    

                        elif shift == 'COMET_NIGHT':    print(f"Testing COMET stage with {len(people)} people ({sum(1 for p in people if p.comet_eligible)} COMET-eligible)")

                            cmn_people.append(person.name)    print(f"COMET week: {config.comet_on_weeks[0]} to {config.comet_on_weeks[0] + timedelta(days=6)}")

                            cmn_count += 1    print(f"Full period: {config.start_date} to {config.end_date}")

                    

                cmd_str = f"CMD: {', '.join(cmd_people)}" if cmd_people else "CMD: NONE"    # Solve COMET stage

                cmn_str = f"CMN: {', '.join(cmn_people)}" if cmn_people else "CMN: NONE"    result = solver.solve_stage("comet", timeout_seconds=60)

                    

                print(f"  {current_day.strftime('%a %Y-%m-%d')}: {cmd_str} | {cmn_str}")    print(f"\nCOMET Stage Result:")

                print(f"Success: {result.success}")

            current_day += timedelta(days=1)    print(f"Message: {result.message}")

            

        print(f"\nTotal COMET assignments in COMET week: {cmd_count} CMD + {cmn_count} CMN = {cmd_count + cmn_count}")    if result.success:

        print("Expected for 7-day COMET week: 7 CMD + 7 CMN = 14 total")        # Count COMET assignments

                cmd_count = 0

        # Show ALL COMET assignments across entire period        cmn_count = 0

        print(f"\nAll COMET assignments across full period ({config.start_date} to {config.end_date}):")        

                # Analyze by day

        current_day = config.start_date        comet_week_start = date(2025, 2, 10)  # Monday

        total_cmd = 0        comet_week_end = comet_week_start + timedelta(days=6)  # Sunday

        total_cmn = 0        

                print(f"\nDaily COMET coverage during COMET week ({comet_week_start} to {comet_week_end}):")

        while current_day <= config.end_date:        

            day_str = current_day.isoformat()        current_day = config.start_date

                    while current_day <= config.end_date:

            cmd_people = []            day_str = current_day.isoformat()

            cmn_people = []            

                        # Check if this day is in COMET week

            for person in people:            is_comet_day = comet_week_start <= current_day <= comet_week_end

                if day_str in result.partial_roster and person.id in result.partial_roster[day_str]:            

                    shift = result.partial_roster[day_str][person.id]            if is_comet_day:

                    if shift == 'COMET_DAY':                cmd_people = []

                        cmd_people.append(person.name)                cmn_people = []

                        total_cmd += 1                

                    elif shift == 'COMET_NIGHT':                for person in people:

                        cmn_people.append(person.name)                    if day_str in result.partial_roster and person.id in result.partial_roster[day_str]:

                        total_cmn += 1                        shift = result.partial_roster[day_str][person.id]

                                    if shift == 'COMET_DAY':

            if cmd_people or cmn_people:                            cmd_people.append(person.name)

                cmd_str = f"CMD: {', '.join(cmd_people)}" if cmd_people else "CMD: -"                            cmd_count += 1

                cmn_str = f"CMN: {', '.join(cmn_people)}" if cmn_people else "CMN: -"                        elif shift == 'COMET_NIGHT':

                is_comet_week = comet_week_start <= current_day <= comet_week_end                            cmn_people.append(person.name)

                week_marker = " [COMET WEEK]" if is_comet_week else ""                            cmn_count += 1

                print(f"  {current_day.strftime('%a %Y-%m-%d')}: {cmd_str} | {cmn_str}{week_marker}")                

                            cmd_str = f"CMD: {', '.join(cmd_people)}" if cmd_people else "CMD: NONE"

            current_day += timedelta(days=1)                cmn_str = f"CMN: {', '.join(cmn_people)}" if cmn_people else "CMN: NONE"

                        

        print(f"\nTotal across all days: {total_cmd} CMD + {total_cmn} CMN = {total_cmd + total_cmn}")                print(f"  {current_day.strftime('%a %Y-%m-%d')}: {cmd_str} | {cmn_str}")

                    

        # Validate coverage            current_day += timedelta(days=1)

        if cmd_count == 7 and cmn_count == 7:        

            print("✅ Perfect COMET coverage: exactly 1 CMD + 1 CMN per day during COMET week")        print(f"\nTotal COMET assignments: {cmd_count} CMD + {cmn_count} CMN = {cmd_count + cmn_count}")

        else:        print(f"Expected for 7-day COMET week: 7 CMD + 7 CMN = 14 total")

            print(f"❌ Incorrect COMET coverage: expected 7 CMD + 7 CMN, got {cmd_count} CMD + {cmn_count} CMN")        

            # Validate coverage

    return result        if cmd_count == 7 and cmn_count == 7:

            print("✅ Perfect COMET coverage: exactly 1 CMD + 1 CMN per day during COMET week")

if __name__ == "__main__":        else:

    test_comet_with_9_people()            print(f"❌ Incorrect COMET coverage: expected 7 CMD + 7 CMN, got {cmd_count} CMD + {cmn_count} CMN")
    
    return result

if __name__ == "__main__":
    test_comet_with_9_people()