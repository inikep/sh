#!/usr/bin/env perl
use strict;
use warnings;
use Encode qw(decode FB_PERLQQ);

binmode(STDIN, ':raw');

my %seen;
my $pending_cmake_source = 0;

while (my $line = <STDIN>) {
    $line = decode('UTF-8', $line, FB_PERLQQ);
    chomp $line;

    if ($pending_cmake_source && $line =~ /\S/) {
        $line =~ s/^\s+|\s+$//g;
        $seen{"cmake:missing-source:$line"} = 1;
        $pending_cmake_source = 0;
        next;
    }

    if ($line =~ /Cannot find source file:/) {
        $pending_cmake_source = 1;
        next;
    }

    if ($line =~ /No SOURCES given to target:\s*(\S+)/) {
        $seen{"cmake:no-sources:$1"} = 1;
        next;
    }

    if ($line =~ /undefined reference to\s+[`'"]?([^`'"\s]+)[`'"]?/) {
        $seen{"undefined:$1"} = 1;
        next;
    }

    if ($line =~ /(?:fatal )?error:\s*(.*)/) {
        my $msg = $1;

        if ($msg =~ /(?:\x{2018}|['"`])([^'"`\x{2019}]+)(?:\x{2019}|['"`]).*(?:not declared|undeclared|no member named|has no member named|was not declared)/) {
            $seen{"symbol:$1"} = 1;
            next;
        }

        $msg =~ s/^\s+|\s+$//g;
        $msg =~ s/\s+at .*//;
        $seen{"error:$msg"} = 1;
        next;
    }

    if ($line =~ /^CMake Error.*\(([^)]+)\):/) {
        $seen{"cmake:$1"} = 1;
        next;
    }
}

print scalar(keys %seen), "\n";
