#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2017-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import os.path

import edgedb

from edb.testbase import server as tb
# from edb.tools import test


class TestEdgeQLPolicies(tb.QueryTestCase):
    '''Tests for policies.'''

    SCHEMA = os.path.join(os.path.dirname(__file__), 'schemas',
                          'issues.esdl')

    SETUP = [
        os.path.join(os.path.dirname(__file__), 'schemas',
                     'issues_setup.edgeql'),
        '''
            # These are for testing purposes and don't really model anything
            create required global cur_owner_active -> bool {
                set default := true;
            };
            create required global watchers_active -> bool {
                set default := true;
            };

            create required global filter_owned -> bool {
                set default := false;
            };
            create global cur_user -> str;

            alter type Owned {
                create access policy disable_filter
                  when (not global filter_owned)
                  allow select;

                create access policy cur_owner
                  when (global cur_owner_active)
                  allow all using (.owner.name ?= global cur_user);
            };

            alter type Issue {
                create access policy cur_watchers
                  when (global watchers_active)
                  allow select using (
                      (global cur_user IN __subject__.watchers.name) ?? false
                  )
            };

            create type CurOnly extending Dictionary {
                create access policy cur_only allow all
                using (not exists global cur_user or global cur_user ?= .name);
            };
            create type CurOnlyM {
                create multi property name -> str {
                    create constraint exclusive;
                };
                create access policy cur_only allow all
                using (
                    not exists global cur_user
                    or (global cur_user in .name) ?? false
                );
            };
        '''
    ]

    async def test_edgeql_policies_01(self):
        await self.con.execute('''
            set global cur_owner_active := false;
        ''')
        await self.con.execute('''
            set global watchers_active := false;
        ''')
        await self.con.execute('''
            set global filter_owned := True;
        ''')

        await self.assert_query_result(
            r'''
                select Owned { [IS Named].name }
            ''',
            []
        )

        await self.assert_query_result(
            r'''
                select Issue { name }
            ''',
            []
        )

    async def test_edgeql_policies_02a(self):
        await self.con.execute('''
            set global cur_user := 'Yury';
        ''')
        await self.con.execute('''
            set global filter_owned := True;
        ''')

        await self.assert_query_result(
            r'''
                select Owned { [IS Named].name }
            ''',
            tb.bag([
                {"name": "Release EdgeDB"},
                {"name": "Improve EdgeDB repl output rendering."},
                {"name": "Repl tweak."},
            ])
        )

        await self.assert_query_result(
            r'''
                select Issue { name }
            ''',
            tb.bag([
                {"name": "Release EdgeDB"},
                {"name": "Improve EdgeDB repl output rendering."},
                {"name": "Repl tweak."},
            ])
        )

    async def test_edgeql_policies_02b(self):
        await self.con.execute('''
            alter type Owned reset abstract;
        ''')

        await self.con.execute('''
            set global cur_user := 'Yury';
        ''')
        await self.con.execute('''
            set global filter_owned := True;
        ''')

        await self.assert_query_result(
            r'''
                select Owned { [IS Named].name }
            ''',
            tb.bag([
                {"name": "Release EdgeDB"},
                {"name": "Improve EdgeDB repl output rendering."},
                {"name": "Repl tweak."},
            ])
        )

        await self.assert_query_result(
            r'''
                select Issue { name }
            ''',
            tb.bag([
                {"name": "Release EdgeDB"},
                {"name": "Improve EdgeDB repl output rendering."},
                {"name": "Repl tweak."},
            ])
        )

    async def test_edgeql_policies_03(self):
        vals = await self.con.query('''
            select Object.id
        ''')
        self.assertEqual(len(vals), len(set(vals)))

        await self.con.execute('''
            create alias foo := Issue;
        ''')

        vals = await self.con.query('''
            select BaseObject.id
        ''')
        self.assertEqual(len(vals), len(set(vals)))

    async def test_edgeql_policies_04(self):
        await self.con.execute('''
            set global cur_user := 'Phil';
        ''')
        await self.con.execute('''
            set global filter_owned := True;
        ''')

        await self.assert_query_result(
            r'''
                select URL { src := .<references[IS User] }
            ''',
            tb.bag([
                {"src": []}
            ])
        )

        await self.assert_query_result(
            r'''
                select URL { src := .<references }
            ''',
            tb.bag([
                {"src": []}
            ])
        )

    async def test_edgeql_policies_05(self):
        await self.con.execute('''
            CREATE TYPE Tgt {
                CREATE REQUIRED PROPERTY b -> bool;

                CREATE ACCESS POLICY redact
                    ALLOW SELECT USING (not global filter_owned);
                CREATE ACCESS POLICY dml_always
                    ALLOW UPDATE, INSERT, DELETE;
            };
            CREATE TYPE Ptr {
                CREATE REQUIRED LINK tgt -> Tgt;
            };
        ''')
        await self.con.query('''
            insert Ptr { tgt := (insert Tgt { b := True }) };
        ''')
        await self.con.execute('''
            set global filter_owned := True;
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.CardinalityViolationError,
                r"returned an empty set"):
            await self.con.query('''
                select Ptr { tgt }
            ''')

        async with self.assertRaisesRegexTx(
                edgedb.CardinalityViolationError,
                r"returned an empty set"):
            await self.con.query('''
                select Ptr { z := .tgt.b }
            ''')

        async with self.assertRaisesRegexTx(
                edgedb.CardinalityViolationError,
                r"returned an empty set"):
            await self.con.query('''
                select Ptr.tgt
            ''')

        async with self.assertRaisesRegexTx(
                edgedb.CardinalityViolationError,
                r"returned an empty set"):
            await self.con.query('''
                select Ptr.tgt.b
            ''')

        await self.con.query('''
            delete Ptr
        ''')

        await self.assert_query_result(
            r''' select Ptr { tgt }''',
            [],
        )

        await self.assert_query_result(
            r''' select Ptr.tgt''',
            [],
        )

        await self.assert_query_result(
            r''' select Ptr.tgt.b''',
            [],
        )

    async def test_edgeql_policies_06(self):
        await self.con.execute('''
            CREATE TYPE Tgt {
                CREATE REQUIRED PROPERTY b -> bool;

                CREATE ACCESS POLICY redact
                    ALLOW SELECT USING (not global filter_owned);
                CREATE ACCESS POLICY dml_always
                    ALLOW UPDATE, INSERT, DELETE;
            };
            CREATE TYPE BadTgt;
            CREATE TYPE Ptr {
                CREATE REQUIRED LINK tgt -> Tgt | BadTgt;
            };
        ''')
        await self.con.query('''
            insert Ptr { tgt := (insert Tgt { b := True }) };
        ''')
        await self.con.execute('''
            set global filter_owned := True;
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.CardinalityViolationError,
                r"returned an empty set"):
            await self.con.query('''
                select Ptr { tgt }
            ''')

    async def test_edgeql_policies_07(self):
        # test update policies
        await self.con.execute('''
            set global filter_owned := True;
        ''')
        await self.con.execute('''
            set global cur_user := 'Yury';
        ''')

        await self.assert_query_result(
            '''
                select Issue { name } filter .number = '1'
            ''',
            [{"name": "Release EdgeDB"}],
        )

        # Shouldn't work
        await self.assert_query_result(
            '''
                update Issue filter .number = '1' set { name := "!" }
            ''',
            [],
        )

        await self.assert_query_result(
            '''
                delete Issue filter .number = '1'
            ''',
            [],
        )

        await self.assert_query_result(
            '''
                select Issue { name } filter .number = '1'
            ''',
            [{"name": "Release EdgeDB"}],
        )

        async with self.assertRaisesRegexTx(
                edgedb.InvalidValueError,
                r"access policy violation on update of default::Issue"):
            await self.con.query('''
                update Issue filter .number = "2"
                set { owner := (select User filter .name = 'Elvis') };
            ''')

        # This update *should* work, though
        await self.assert_query_result(
            '''
                update Issue filter .number = '2' set { name := "!" }
            ''',
            [{}],
        )

        await self.assert_query_result(
            '''
                select Issue { name } filter .number = '2'
            ''',
            [{"name": "!"}],
        )

        # Now try updating Named, based on name

        # This one should work
        await self.assert_query_result(
            '''
                update Named filter .name = '!' set { name := "Fix bug" }
            ''',
            [{}],
        )

        await self.assert_query_result(
            '''
                select Issue { name } filter .number = '2'
            ''',
            [{"name": "Fix bug"}],
        )

        # This shouldn't work
        await self.assert_query_result(
            '''
                update Named filter .name = 'Release EdgeDB'
                set { name := "?" }
            ''',
            [],
        )

        await self.assert_query_result(
            '''
                select Issue { name } filter .number = '1'
            ''',
            [{"name": "Release EdgeDB"}],
        )

        async with self.assertRaisesRegexTx(
                edgedb.InvalidValueError,
                "access policy violation"):
            await self.con.query('''
                INSERT Issue {
                    number := '4',
                    name := 'Regression.',
                    body := 'Fix regression introduced by lexer tweak.',
                    owner := (SELECT User FILTER User.name = 'Elvis'),
                    status := (SELECT Status FILTER Status.name = 'Closed'),
                } UNLESS CONFLICT ON (.number) ELSE Issue;
            ''')

    async def test_edgeql_policies_08(self):
        async with self.assertRaisesRegexTx(
                edgedb.QueryError,
                r"possibly an empty set"):
            await self.con.query('''
                WITH Z := (INSERT Issue {
                    number := '4',
                    name := 'Regression.',
                    body := 'Fix regression introduced by lexer tweak.',
                    owner := (SELECT User FILTER User.name = 'Elvis'),
                    status := (SELECT Status FILTER Status.name = 'Closed'),
                } UNLESS CONFLICT ON (.number) ELSE Issue),
                select { required z := Z };
            ''')

    async def test_edgeql_policies_09(self):
        # Create a type that we can write but not view
        await self.con.execute('''
            create type X extending Dictionary {
                create access policy can_insert allow insert;
            };
            insert X { name := "!" };
        ''')

        # We need to raise a constraint violation error even though
        # we are trying to do unless conflict, because we can't see
        # the conflicting object!
        async with self.assertRaisesRegexTx(
                edgedb.ConstraintViolationError,
                r"name violates exclusivity constraint"):
            await self.con.query('''
                insert X { name := "!" }
                unless conflict on (.name) else (select X)
            ''')

    async def test_edgeql_policies_order_01(self):
        await self.con.execute('''
            insert CurOnly { name := "!" }
        ''')
        await self.con.execute('''
            set global cur_user := "?"
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.InvalidValueError,
                r"access policy violation on insert of default::CurOnly"):
            await self.con.query('''
                insert CurOnly { name := "!" }
            ''')

    async def test_edgeql_policies_order_02(self):
        await self.con.execute('''
            insert CurOnly { name := "!" };
            insert CurOnly { name := "?" };
        ''')
        await self.con.execute('''
            set global cur_user := "?"
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.InvalidValueError,
                r"access policy violation on update of default::CurOnly"):
            await self.con.query('''
                update CurOnly set { name := "!" }
            ''')

    async def test_edgeql_policies_order_03(self):
        await self.con.execute('''
            insert CurOnlyM { name := "!" }
        ''')
        await self.con.execute('''
            set global cur_user := "?"
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.InvalidValueError,
                r"access policy violation on insert of default::CurOnlyM"):
            await self.con.query('''
                insert CurOnlyM { name := "!" }
            ''')

    async def test_edgeql_policies_order_04(self):
        await self.con.execute('''
            insert CurOnlyM { name := "!" };
            insert CurOnlyM { name := "?" };
        ''')
        await self.con.execute('''
            set global cur_user := "?"
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.InvalidValueError,
                r"access policy violation on update of default::CurOnlyM"):
            await self.con.query('''
                update CurOnlyM set { name := "!" }
            ''')

    async def test_edgeql_policies_scope_01(self):
        await self.con.execute('''
            create type Foo {
                create required property val -> int64;
            };
        ''')

        async with self.assertRaisesRegexTx(
                edgedb.SchemaDefinitionError,
                r'possibly an empty set returned'):
            await self.con.execute('''
                alter type Foo {
                    create access policy pol allow all using(Foo.val > 5);
                };
            ''')

    async def test_edgeql_policies_binding_01(self):
        await self.con.execute('''
            CREATE TYPE Foo {
                CREATE REQUIRED PROPERTY val -> int64;
            };
            CREATE TYPE Bar EXTENDING Foo;
            ALTER TYPE Foo {
                CREATE ACCESS POLICY ap0
                    ALLOW ALL USING ((count(Bar) = 0));
            };
        ''')

        await self.con.execute('''
            insert Foo { val := 0 };
            insert Foo { val := 1 };
            insert Bar { val := 10 };
        ''')

        await self.assert_query_result(
            r'''
                select Foo
            ''',
            []
        )

        await self.assert_query_result(
            r'''
                select Bar
            ''',
            []
        )

    async def test_edgeql_policies_binding_02(self):
        await self.con.execute('''
            CREATE TYPE Foo {
                CREATE REQUIRED PROPERTY val -> int64;
            };
            CREATE TYPE Bar EXTENDING Foo;
            ALTER TYPE Foo {
                CREATE ACCESS POLICY ins ALLOW INSERT;
                CREATE ACCESS POLICY ap0
                    ALLOW ALL USING (
                        not exists (select Foo filter .val = 1));
            };
        ''')

        await self.con.execute('''
            insert Foo { val := 0 };
            insert Foo { val := 1 };
            insert Bar { val := 10 };
        ''')

        await self.assert_query_result(
            r'''
                select Foo
            ''',
            []
        )

        await self.assert_query_result(
            r'''
                select Bar
            ''',
            []
        )

    async def test_edgeql_policies_binding_03(self):
        await self.con.execute('''
            CREATE TYPE Foo {
                CREATE REQUIRED PROPERTY val -> int64;
            };
            CREATE TYPE Bar EXTENDING Foo;
            ALTER TYPE Foo {
                CREATE MULTI LINK bar -> Bar;
            };

            insert Foo { val := 0 };
            insert Foo { val := 1 };
            insert Bar { val := 10 };
            update Foo set { bar := Bar };

            ALTER TYPE Foo {
                CREATE ACCESS POLICY ap0
                    ALLOW ALL USING (not exists .bar);
            };
        ''')

        await self.assert_query_result(
            r'''
                select Foo
            ''',
            []
        )

        await self.assert_query_result(
            r'''
                select Bar
            ''',
            []
        )

    async def test_edgeql_policies_binding_04(self):
        await self.con.execute('''
            CREATE TYPE Foo {
                CREATE REQUIRED PROPERTY val -> int64;
                CREATE MULTI LINK foo -> Foo;
            };
            CREATE TYPE Bar EXTENDING Foo;

            insert Foo { val := 0 };
            insert Foo { val := 1 };
            insert Bar { val := 10 };
            update Foo set { foo := Foo };

            ALTER TYPE Foo {
                CREATE ACCESS POLICY ap0
                    ALLOW ALL USING (not exists .foo);
            };
        ''')

        await self.assert_query_result(
            r'''
                select Foo
            ''',
            []
        )

        await self.assert_query_result(
            r'''
                select Bar
            ''',
            []
        )

    async def test_edgeql_policies_cycle_01(self):
        async with self.assertRaisesRegexTx(
            edgedb.SchemaDefinitionError,
            r"dependency cycle between access policies of object type "
            r"'default::Bar' and object type 'default::Foo'"
        ):
            await self.con.execute("""
                CREATE TYPE Bar {
                    CREATE REQUIRED PROPERTY b -> bool;
                };
                CREATE TYPE Foo {
                    CREATE LINK bar -> Bar;
                    CREATE REQUIRED PROPERTY b -> bool;
                    CREATE ACCESS POLICY redact
                        ALLOW ALL USING ((.bar.b ?? false));
                };
                ALTER TYPE Bar {
                    CREATE LINK foo -> Foo;
                    CREATE ACCESS POLICY redact
                        ALLOW ALL USING ((.foo.b ?? false));
                };
            """)

    async def test_edgeql_policies_cycle_02(self):
        # This is a cycle because Bar selecting Foo requires indirectly
        # evaluating Bar as part of doing Foo in a way we can't handle
        async with self.assertRaisesRegexTx(
                edgedb.InvalidDefinitionError,
                r"dependency cycle between access policies"):
            await self.con.execute('''
                create type Foo {
                    create required property val -> int64;
                };
                create type Bar extending Foo {
                  create access policy x allow all using (
                    not exists (select Foo filter .val = -__subject__.val));
                };
            ''')

    async def test_edgeql_policies_cycle_03(self):
        async with self.assertRaisesRegexTx(
                edgedb.InvalidDefinitionError,
                r"dependency cycle between access policies"):
            await self.con.execute('''
                create type Z;
                create type A {
                    create access policy z allow all using (exists Z);
                };
                create type B extending A;
                alter type Z {
                    create access policy z allow all using (exists B);
                };
            ''')

    async def test_edgeql_policies_cycle_04(self):
        async with self.assertRaisesRegexTx(
                edgedb.InvalidDefinitionError,
                r"dependency cycle between access policies"):
            await self.con.execute('''
                create type Z;
                create type A {
                    create access policy z allow all using (exists Z);
                };
                create type C;
                create type B extending A, C;
                alter type Z {
                    create access policy z allow all using (exists C);
                };
            ''')
